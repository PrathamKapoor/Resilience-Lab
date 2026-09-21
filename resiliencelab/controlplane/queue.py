"""Redis-backed job queue for experiment execution."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, cast

import redis

_queue_key = "resiliencelab:jobs:pending"
_processing_key = "resiliencelab:jobs:processing"
_results_key = "resiliencelab:jobs:results"
_job_prefix = "resiliencelab:job:"


def _resolve_redis_url() -> str:
    return os.environ.get("RESILIENCELAB_REDIS_URL", "redis://127.0.0.1:6379/0")


def get_redis_client(url: str | None = None) -> redis.Redis:
    resolved = url or _resolve_redis_url()
    return redis.Redis.from_url(resolved, decode_responses=True)


@dataclass
class JobPayload:
    experiment_id: str
    run_id: str
    run_index: int
    seed: int
    config_yaml: str
    config_hash: str
    worker_id: str = ""
    created_at: float = field(default_factory=time.time)
    claimed_at: float | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "experiment_id": self.experiment_id,
                "run_id": self.run_id,
                "run_index": self.run_index,
                "seed": self.seed,
                "config_yaml": self.config_yaml,
                "config_hash": self.config_hash,
                "worker_id": self.worker_id,
                "created_at": self.created_at,
                "claimed_at": self.claimed_at,
            }
        )

    @classmethod
    def from_json(cls, data: str) -> JobPayload:
        d = json.loads(data)
        return cls(
            experiment_id=d["experiment_id"],
            run_id=d["run_id"],
            run_index=d["run_index"],
            seed=d["seed"],
            config_yaml=d["config_yaml"],
            config_hash=d["config_hash"],
            worker_id=d.get("worker_id", ""),
            created_at=d.get("created_at", time.time()),
            claimed_at=d.get("claimed_at"),
        )


def enqueue_experiment(
    r: redis.Redis,
    experiment_id: str,
    config_yaml: str,
    config_hash: str,
    num_runs: int,
) -> list[str]:
    job_ids: list[str] = []
    pipe = r.pipeline()
    for i in range(num_runs):
        job_id = f"{experiment_id}/run-{i}"
        payload = JobPayload(
            experiment_id=experiment_id,
            run_id=job_id,
            run_index=i,
            seed=0,
            config_yaml=config_yaml,
            config_hash=config_hash,
        )
        pipe.hset(_job_prefix + job_id, mapping={"payload": payload.to_json(), "status": "QUEUED"})
        pipe.lpush(_queue_key, job_id)
        job_ids.append(job_id)
    pipe.execute()
    return job_ids


def claim_job(r: redis.Redis, worker_id: str, timeout: int = 30) -> JobPayload | None:
    result = r.brpoplpush(_queue_key, _processing_key, timeout=timeout)
    if result is None:
        return None
    job_id = result if isinstance(result, str) else result.decode()  # type: ignore[attr-defined,unused-ignore]
    data = r.hget(_job_prefix + job_id, "payload")
    if data is None:
        r.lrem(_processing_key, 1, job_id)
        return None
    payload = JobPayload.from_json(data)  # type: ignore[arg-type]
    payload.worker_id = worker_id
    payload.claimed_at = time.time()
    pipe = r.pipeline()
    pipe.hset(
        _job_prefix + job_id,
        mapping={
            "payload": payload.to_json(),
            "status": "RUNNING",
            "worker_id": worker_id,
        },
    )
    pipe.execute()
    return payload


def complete_job(
    r: redis.Redis, job_id: str, status: str, artifact_path: str | None = None
) -> None:
    # redis-py's stubs type ``mapping`` differently across releases, so keep it loose.
    mapping: dict[Any, Any] = {"status": status}
    if artifact_path:
        mapping["artifact_path"] = artifact_path
    pipe = r.pipeline()
    pipe.hset(_job_prefix + job_id, mapping=mapping)
    pipe.lrem(_processing_key, 1, job_id)
    pipe.execute()


def requeue_stuck_jobs(r: redis.Redis, max_age_seconds: int = 600) -> int:
    stuck: list[str] = []
    for item in cast(list[str | bytes], r.lrange(_processing_key, 0, -1)):
        job_id = item if isinstance(item, str) else item.decode()
        data = r.hget(_job_prefix + job_id, "payload")
        if data is None:
            stuck.append(job_id)
            continue
        # Skip cancelled jobs — don't requeue them
        job_status = r.hget(_job_prefix + job_id, "status")
        if job_status == "CANCELLED":
            r.lrem(_processing_key, 1, job_id)
            continue
        payload = JobPayload.from_json(data)  # type: ignore[arg-type]
        if payload.claimed_at and (time.time() - payload.claimed_at) > max_age_seconds:
            stuck.append(job_id)
    if not stuck:
        return 0
    pipe = r.pipeline()
    for job_id in stuck:
        pipe.lrem(_processing_key, 1, job_id)
        pipe.lpush(_queue_key, job_id)
        pipe.hset(_job_prefix + job_id, mapping={"status": "QUEUED"})
    pipe.execute()
    return len(stuck)


def get_job_status(r: redis.Redis, job_id: str) -> str | None:
    return r.hget(_job_prefix + job_id, "status")  # type: ignore[return-value]
