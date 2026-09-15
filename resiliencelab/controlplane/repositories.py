"""Repository for experiment persistence with atomic state transitions.

State model:
    CREATED -> QUEUED -> RUNNING -> COMPLETED
    RUNNING -> CANCEL_REQUESTED -> CANCELLED
    CREATED/QUEUED -> CANCELLED (immediate, before worker claim)

Terminal states (immutable):
    COMPLETED, FAILED, CANCELLED

Race semantics:
    - If completion wins the atomic terminal-state race, the run is COMPLETED.
    - If cancellation wins before completion commits, the run is CANCELLED.
    - Terminal states cannot be overwritten.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from resiliencelab.controlplane.models import ExperimentRecord, RunRecord

# States that cannot be changed once reached
TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


def _is_terminal(status: Any) -> bool:
    return str(status) in TERMINAL_STATES


def create_experiment(
    session: Session,
    *,
    experiment_id: str,
    name: str,
    version: int,
    description: str,
    config_yaml: str,
    config_hash: str,
    status: str = "CREATED",
    owner_id: str | None = None,
) -> ExperimentRecord:
    record = ExperimentRecord(
        experiment_id=experiment_id,
        name=name,
        version=version,
        description=description,
        config_yaml=config_yaml,
        config_hash=config_hash,
        status=status,
        owner_id=owner_id,
    )
    session.add(record)
    session.flush()
    return record


def get_experiment(session: Session, experiment_id: str) -> ExperimentRecord | None:
    return session.get(ExperimentRecord, experiment_id)


def get_experiment_by_hash(session: Session, config_hash: str) -> ExperimentRecord | None:
    return session.execute(
        select(ExperimentRecord).where(ExperimentRecord.config_hash == config_hash)
    ).scalar_one_or_none()


def list_experiments(
    session: Session,
    *,
    status: str | None = None,
    owner_id: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[ExperimentRecord]:
    q = select(ExperimentRecord).order_by(ExperimentRecord.created_at.desc())
    if status:
        q = q.where(ExperimentRecord.status == status)
    if owner_id:
        q = q.where(ExperimentRecord.owner_id == owner_id)
    q = q.offset(offset).limit(limit)
    return list(session.execute(q).scalars().all())


def count_experiments(
    session: Session,
    *,
    status: str | None = None,
    owner_id: str | None = None,
) -> int:
    from sqlalchemy import func

    q = select(func.count()).select_from(ExperimentRecord)
    if status:
        q = q.where(ExperimentRecord.status == status)
    if owner_id:
        q = q.where(ExperimentRecord.owner_id == owner_id)
    return session.execute(q).scalar_one()


def update_experiment_status(
    session: Session,
    experiment_id: str,
    status: str,
    *,
    artifact_path: str | None = None,
    error_message: str | None = None,
) -> None:
    values: dict[str, Any] = {"status": status, "updated_at": dt.datetime.now(dt.UTC)}
    if artifact_path is not None:
        values["artifact_path"] = artifact_path
    if error_message is not None:
        values["error_message"] = error_message
    session.execute(
        update(ExperimentRecord)
        .where(ExperimentRecord.experiment_id == experiment_id)
        .values(**values)
    )


def request_cancel(
    session: Session,
    experiment_id: str,
    reason: str = "",
) -> tuple[bool, str]:
    """Atomically request cancellation of an experiment.

    Returns (success, message):
        - (True, "cancel_requested"): RUNNING -> CANCEL_REQUESTED
        - (True, "cancelled"): CREATED/QUEUED -> CANCELLED (immediate)
        - (False, "not_found"): experiment does not exist
        - (False, "already_terminal"): already COMPLETED/FAILED/CANCELLED
        - (False, "already_cancel_requested"): already CANCEL_REQUESTED

    The caller should NOT treat (False, "already_terminal") as an error.
    It means the experiment reached a terminal state before or during the request.
    """
    record = get_experiment(session, experiment_id)
    if record is None:
        return False, "not_found"

    now = dt.datetime.now(dt.UTC)
    current_status = cast(str, record.status)

    # Terminal states are immutable
    if _is_terminal(current_status):
        return False, f"already_{current_status.lower()}"

    # Already requested
    if current_status == "CANCEL_REQUESTED":
        return False, "already_cancel_requested"

    # Immediate cancellation for CREATED/QUEUED (before worker claim)
    if current_status in ("CREATED", "QUEUED"):
        record.status = "CANCELLED"  # type: ignore[assignment]
        record.cancellation_reason = reason or "user requested"  # type: ignore[assignment]
        record.cancelled_at = now  # type: ignore[assignment]
        record.updated_at = now  # type: ignore[assignment]
        return True, "cancelled"

    # RUNNING -> CANCEL_REQUESTED (worker will observe and complete cancellation)
    if current_status == "RUNNING":
        record.status = "CANCEL_REQUESTED"  # type: ignore[assignment]
        record.cancellation_reason = reason or "user requested"  # type: ignore[assignment]
        record.updated_at = now  # type: ignore[assignment]
        return True, "cancel_requested"

    return False, f"unexpected_status_{current_status.lower()}"


def mark_cancelled(
    session: Session,
    experiment_id: str,
    reason: str = "",
) -> None:
    """Mark an experiment as CANCELLED (called by worker after runner stops)."""
    now = dt.datetime.now(dt.UTC)
    record = get_experiment(session, experiment_id)
    if record is None:
        return
    # Only update if not already in a terminal state (atomic race protection)
    if not _is_terminal(record.status):
        record.status = "CANCELLED"  # type: ignore[assignment]
        existing_reason = (
            cast(str, record.cancellation_reason) if record.cancellation_reason else ""
        )
        record.cancellation_reason = reason or existing_reason or "worker cancelled"  # type: ignore[assignment]
        record.cancelled_at = now  # type: ignore[assignment]
        record.updated_at = now  # type: ignore[assignment]


def mark_run_cancelled(
    session: Session,
    run_id: str,
    reason: str = "",
) -> None:
    """Mark a run as CANCELLED (called by worker after runner stops)."""
    now = dt.datetime.now(dt.UTC)
    run_record = session.get(RunRecord, run_id)
    if run_record is None:
        return
    if not _is_terminal(run_record.status):
        run_record.status = "CANCELLED"  # type: ignore[assignment]
        run_record.cancellation_reason = reason or "worker cancelled"  # type: ignore[assignment]
        run_record.cancelled_at = now  # type: ignore[assignment]
        run_record.completed_at = now  # type: ignore[assignment]


def check_cancel_requested(session: Session, experiment_id: str) -> bool:
    """Check if an experiment has a pending cancellation request.

    Used by the worker to poll for cancellation during execution.
    Returns True if status is CANCEL_REQUESTED.
    """
    record = get_experiment(session, experiment_id)
    return record is not None and cast(str, record.status) == "CANCEL_REQUESTED"


def get_runs(session: Session, experiment_id: str) -> list[RunRecord]:
    return list(
        session.execute(
            select(RunRecord)
            .where(RunRecord.experiment_id == experiment_id)
            .order_by(RunRecord.run_index)
        )
        .scalars()
        .all()
    )


# Keep backward compatibility
def cancel_experiment(session: Session, experiment_id: str) -> bool:
    """Legacy cancel: returns True if cancellation was applied."""
    success, _message = request_cancel(session, experiment_id)
    return success
