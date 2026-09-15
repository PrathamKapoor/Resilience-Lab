"""Worker that processes experiment jobs from the Redis queue."""

from __future__ import annotations

import datetime as dt
import logging
import signal
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
    update_experiment_status,
)
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
        _process_job(r, runner, payload)
        jobs_processed += 1

    logger.info("Worker %s stopped after %d jobs", worker_id, jobs_processed)


def _process_job(
    r: redis.Redis,
    runner: ExperimentRunner,
    payload: JobPayload,
) -> None:
    session = create_session()
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

        spec_data = yaml.safe_load(payload.config_yaml)
        spec = parse_experiment(spec_data)
        result = runner.run(spec)

        artifact_dir = f"results/{payload.experiment_id}/runs/{payload.run_id}"
        write_artifacts(result, Path(artifact_dir))

        with session.begin():
            run_record = session.get(RunRecord, payload.run_id)
            if run_record:
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

    except Exception as exc:
        logger.exception("Job %s failed: %s", payload.run_id, exc)
        session.rollback()
        try:
            with session.begin():
                run_record = session.get(RunRecord, payload.run_id)
                if run_record:
                    run_record.status = "FAILED"  # type: ignore[assignment]
                    run_record.error_message = str(exc)[:2000]  # type: ignore[assignment]
                    run_record.completed_at = dt.datetime.now(dt.UTC)  # type: ignore[assignment]
            complete_job(r, payload.run_id, "FAILED")
        except Exception:
            logger.exception("Failed to record failure for %s", payload.run_id)
        session.close()
