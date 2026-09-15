"""Worker that processes experiment jobs from the Redis queue.

Cancellation semantics:
    - Worker creates a CancellationToken for each job.
    - Worker polls DB every `cancel_poll_interval` seconds to check for CANCEL_REQUESTED.
    - When CANCEL_REQUESTED is detected, the token is set, and the runner cooperatively stops.
    - Worker maps CancelledError to CANCELLED status (not FAILED).
    - Stale jobs for cancelled runs are skipped (DB is authoritative).
    - Terminal states (COMPLETED/FAILED/CANCELLED) are never overwritten.
"""

from __future__ import annotations

import datetime as dt
import logging
import signal
import threading
import uuid
from pathlib import Path

import redis
import yaml
from sqlalchemy import select

from resiliencelab.controlplane.database import create_session, init_session_factory
from resiliencelab.controlplane.models import RunRecord
from resiliencelab.controlplane.queue import (
    JobPayload,
    claim_job,
    complete_job,
    get_redis_client,
    requeue_stuck_jobs,
)
from resiliencelab.controlplane.repositories import (
    check_cancel_requested,
    get_experiment,
    mark_cancelled,
    mark_run_cancelled,
    update_experiment_status,
)
from resiliencelab.core.cancellation import CancellationToken, CancelledError
from resiliencelab.core.config import parse_experiment
from resiliencelab.experiments.artifacts import write_artifacts
from resiliencelab.experiments.runner import ExperimentRunner

logger = logging.getLogger(__name__)

_running = True


def _handle_signal(signum: int, frame: object) -> None:
    global _running
    logger.info("Received signal %s, shutting down gracefully...", signum)
    _running = False


def run_worker(
    worker_id: str | None = None,
    redis_url: str | None = None,
    db_url: str | None = None,
    poll_interval: int = 5,
    max_jobs: int | None = None,
    cancel_poll_interval: float = 2.0,
) -> None:
    global _running
    _running = True

    worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    logger.info("Starting worker %s", worker_id)

    r = get_redis_client(redis_url)
    init_session_factory(db_url)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    jobs_processed = 0
    runner = ExperimentRunner()

    while _running:
        if max_jobs and jobs_processed >= max_jobs:
            logger.info("Reached max_jobs=%d, stopping", max_jobs)
            break

        requeue_stuck_jobs(r)

        payload = claim_job(r, worker_id, timeout=poll_interval)
        if payload is None:
            continue

        logger.info("Claimed job %s", payload.run_id)

        # Check if experiment was cancelled before we started processing
        if _is_cancelled_before_start(payload.experiment_id, payload.run_id):
            logger.info("Job %s skipped: experiment already cancelled", payload.run_id)
            _skip_cancelled_job(r, runner, payload)
            jobs_processed += 1
            continue

        _process_job(r, runner, payload, cancel_poll_interval)
        jobs_processed += 1

    logger.info("Worker %s stopped after %d jobs", worker_id, jobs_processed)


def _is_cancelled_before_start(experiment_id: str, run_id: str) -> bool:
    """Check if experiment or run is already cancelled before processing."""
    session = create_session()
    try:
        exp = get_experiment(session, experiment_id)
        if exp is not None and exp.status in ("CANCELLED", "CANCEL_REQUESTED"):
            return True
        run_record = session.get(RunRecord, run_id)
        return bool(run_record is not None and run_record.status == "CANCELLED")
    finally:
        session.close()


def _skip_cancelled_job(
    r: redis.Redis,
    runner: ExperimentRunner,
    payload: JobPayload,
) -> None:
    """Handle a job that was cancelled before we started processing."""
    session = create_session()
    try:
        # Mark run as cancelled if it exists and isn't terminal
        mark_run_cancelled(session, payload.run_id, reason="cancelled before execution")
        session.commit()
        complete_job(r, payload.run_id, "CANCELLED")
        logger.info("Skipped cancelled job %s", payload.run_id)
    except Exception:
        logger.exception("Failed to skip cancelled job %s", payload.run_id)
        session.rollback()
    finally:
        session.close()


def _process_job(
    r: redis.Redis,
    runner: ExperimentRunner,
    payload: JobPayload,
    cancel_poll_interval: float = 2.0,
) -> None:
    session = create_session()
    cancellation_token = CancellationToken()
    cancel_checker: threading.Thread | None = None

    def _poll_cancellation() -> None:
        """Background thread that polls DB for cancellation requests."""
        while not cancellation_token.is_cancelled:
            try:
                if check_cancel_requested(session, payload.experiment_id):
                    logger.info(
                        "Cancellation requested for %s, signaling token",
                        payload.experiment_id,
                    )
                    cancellation_token.request(reason="user requested")
                    return
            except Exception:
                logger.debug("Error polling cancellation for %s", payload.experiment_id)
            # Sleep in small increments so we can stop quickly
            for _ in range(int(cancel_poll_interval * 10)):
                if cancellation_token.is_cancelled:
                    return
                import time

                time.sleep(0.1)

    try:
        update_experiment_status(session, payload.experiment_id, "RUNNING")
        run_record = session.get(RunRecord, payload.run_id)
        if run_record is None:
            run_record = RunRecord(
                run_id=payload.run_id,
                experiment_id=payload.experiment_id,
                run_index=payload.run_index,
                seed=payload.seed,
                status="RUNNING",
                started_at=dt.datetime.now(dt.UTC),
            )
            session.add(run_record)
        else:
            run_record.status = "RUNNING"  # type: ignore[assignment]
            run_record.started_at = dt.datetime.now(dt.UTC)  # type: ignore[assignment]
        session.commit()

        # Start background cancellation polling
        cancel_checker = threading.Thread(target=_poll_cancellation, daemon=True)
        cancel_checker.start()

        spec_data = yaml.safe_load(payload.config_yaml)
        spec = parse_experiment(spec_data)
        result = runner.run(spec, cancellation_token=cancellation_token)

        # Check if cancellation was the cause
        if result.cancelled:
            artifact_dir = f"results/{payload.experiment_id}/runs/{payload.run_id}"
            write_artifacts(result, Path(artifact_dir))

            with session.begin():
                run_record = session.get(RunRecord, payload.run_id)
                if run_record and run_record.status not in ("COMPLETED", "FAILED", "CANCELLED"):
                    run_record.status = "CANCELLED"  # type: ignore[assignment]
                    run_record.completed_at = dt.datetime.now(dt.UTC)  # type: ignore[assignment]
                    run_record.artifact_path = artifact_dir  # type: ignore[assignment]
                    reason_str: str = result.cancellation_reason or "worker cancelled"
                    run_record.cancellation_reason = reason_str  # type: ignore[assignment]
                    run_record.cancelled_at = dt.datetime.now(dt.UTC)  # type: ignore[assignment]

            mark_cancelled(session, payload.experiment_id, result.cancellation_reason)
            session.commit()

            complete_job(r, payload.run_id, "CANCELLED", artifact_dir)
            logger.info("Cancelled job %s", payload.run_id)
            return

        artifact_dir = f"results/{payload.experiment_id}/runs/{payload.run_id}"
        write_artifacts(result, Path(artifact_dir))

        with session.begin():
            run_record = session.get(RunRecord, payload.run_id)
            if run_record and run_record.status not in ("COMPLETED", "FAILED", "CANCELLED"):
                run_record.status = "COMPLETED"  # type: ignore[assignment]
                run_record.completed_at = dt.datetime.now(dt.UTC)  # type: ignore[assignment]
                run_record.artifact_path = artifact_dir  # type: ignore[assignment]

            all_runs = (
                session.execute(
                    select(RunRecord).where(RunRecord.experiment_id == payload.experiment_id)
                )
                .scalars()
                .all()
            )
            if all(r.status == "COMPLETED" for r in all_runs):
                update_experiment_status(
                    session, payload.experiment_id, "COMPLETED", artifact_path=artifact_dir
                )

        complete_job(r, payload.run_id, "COMPLETED", artifact_dir)
        logger.info("Completed job %s", payload.run_id)

    except CancelledError as exc:
        logger.info("Job %s cancelled: %s", payload.run_id, exc)
        session.rollback()
        try:
            artifact_dir = f"results/{payload.experiment_id}/runs/{payload.run_id}"
            # Try to write partial artifacts if we have partial results
            with session.begin():
                run_record = session.get(RunRecord, payload.run_id)
                if run_record and run_record.status not in ("COMPLETED", "FAILED", "CANCELLED"):
                    run_record.status = "CANCELLED"  # type: ignore[assignment]
                    run_record.completed_at = dt.datetime.now(dt.UTC)  # type: ignore[assignment]
                    run_record.cancellation_reason = str(exc)  # type: ignore[assignment]
                    run_record.cancelled_at = dt.datetime.now(dt.UTC)  # type: ignore[assignment]
            mark_cancelled(session, payload.experiment_id, str(exc))
            session.commit()
            complete_job(r, payload.run_id, "CANCELLED")
        except Exception:
            logger.exception("Failed to record cancellation for %s", payload.run_id)
            session.rollback()
        session.close()

    except Exception as exc:
        logger.exception("Job %s failed: %s", payload.run_id, exc)
        session.rollback()
        try:
            with session.begin():
                run_record = session.get(RunRecord, payload.run_id)
                if run_record and run_record.status not in ("COMPLETED", "FAILED", "CANCELLED"):
                    run_record.status = "FAILED"  # type: ignore[assignment]
                    run_record.error_message = str(exc)[:2000]  # type: ignore[assignment]
                    run_record.completed_at = dt.datetime.now(dt.UTC)  # type: ignore[assignment]
            complete_job(r, payload.run_id, "FAILED")
        except Exception:
            logger.exception("Failed to record failure for %s", payload.run_id)
        session.close()

    finally:
        if cancel_checker is not None and cancel_checker.is_alive():
            cancellation_token.request(reason="cleanup")
            cancel_checker.join(timeout=2.0)
