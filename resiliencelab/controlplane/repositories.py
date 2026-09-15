"""Repository for experiment persistence."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from resiliencelab.controlplane.models import ExperimentRecord, RunRecord


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
) -> ExperimentRecord:
    record = ExperimentRecord(
        experiment_id=experiment_id,
        name=name,
        version=version,
        description=description,
        config_yaml=config_yaml,
        config_hash=config_hash,
        status=status,
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
    offset: int = 0,
    limit: int = 100,
) -> list[ExperimentRecord]:
    q = select(ExperimentRecord).order_by(ExperimentRecord.created_at.desc())
    if status:
        q = q.where(ExperimentRecord.status == status)
    q = q.offset(offset).limit(limit)
    return list(session.execute(q).scalars().all())


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


def cancel_experiment(session: Session, experiment_id: str) -> bool:
    record = get_experiment(session, experiment_id)
    if record is None:
        return False
    if record.status in ("CREATED", "QUEUED"):
        update_experiment_status(session, experiment_id, "CANCELLED")
        return True
    if record.status == "RUNNING":
        update_experiment_status(session, experiment_id, "CANCEL_REQUESTED")
        return True
    return False


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
