"""Tests for the control plane: DB, queue, worker, API server mode."""

from __future__ import annotations

import time

import pytest
import redis

from resiliencelab.controlplane.database import get_engine
from resiliencelab.controlplane.models import Base, RunRecord
from resiliencelab.controlplane.queue import (
    JobPayload,
    claim_job,
    complete_job,
    enqueue_experiment,
    get_job_status,
    get_redis_client,
    requeue_stuck_jobs,
)
from resiliencelab.controlplane.repositories import (
    cancel_experiment,
    create_experiment,
    get_experiment,
    get_runs,
    list_experiments,
    update_experiment_status,
)


@pytest.fixture()
def engine():
    eng = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = session_factory()
    yield s
    s.close()


@pytest.fixture()
def redis_client():
    try:
        r = get_redis_client("redis://127.0.0.1:6379/15")
        r.ping()
        r.flushdb()
        yield r
        r.flushdb()
    except redis.ConnectionError:
        pytest.skip("Redis not available")


class TestModels:
    def test_experiment_record_creation(self, session):
        record = create_experiment(
            session,
            experiment_id="exp_test",
            name="test experiment",
            version=1,
            description="desc",
            config_yaml="test: true",
            config_hash="abc123",
        )
        assert record.experiment_id == "exp_test"
        assert record.status == "CREATED"

    def test_get_experiment(self, session):
        create_experiment(
            session,
            experiment_id="exp_get",
            name="get test",
            version=1,
            description="",
            config_yaml="x: 1",
            config_hash="hash1",
        )
        found = get_experiment(session, "exp_get")
        assert found is not None
        assert found.name == "get test"

    def test_get_experiment_missing(self, session):
        assert get_experiment(session, "nonexistent") is None

    def test_list_experiments(self, session):
        for i in range(3):
            create_experiment(
                session,
                experiment_id=f"exp_{i}",
                name=f"test {i}",
                version=1,
                description="",
                config_yaml="x: 1",
                config_hash=f"hash_{i}",
            )
        all_exps = list_experiments(session)
        assert len(all_exps) == 3

    def test_list_experiments_by_status(self, session):
        create_experiment(
            session,
            experiment_id="exp_a",
            name="a",
            version=1,
            description="",
            config_yaml="x: 1",
            config_hash="h1",
            status="QUEUED",
        )
        create_experiment(
            session,
            experiment_id="exp_b",
            name="b",
            version=1,
            description="",
            config_yaml="x: 1",
            config_hash="h2",
            status="COMPLETED",
        )
        queued = list_experiments(session, status="QUEUED")
        assert len(queued) == 1
        assert queued[0].experiment_id == "exp_a"

    def test_update_status(self, session):
        create_experiment(
            session,
            experiment_id="exp_upd",
            name="upd",
            version=1,
            description="",
            config_yaml="x: 1",
            config_hash="h",
        )
        update_experiment_status(session, "exp_upd", "RUNNING")
        record = get_experiment(session, "exp_upd")
        assert record.status == "RUNNING"

    def test_cancel_queued(self, session):
        create_experiment(
            session,
            experiment_id="exp_cq",
            name="cq",
            version=1,
            description="",
            config_yaml="x: 1",
            config_hash="h",
            status="QUEUED",
        )
        assert cancel_experiment(session, "exp_cq") is True
        record = get_experiment(session, "exp_cq")
        assert record.status == "CANCELLED"

    def test_cancel_running(self, session):
        create_experiment(
            session,
            experiment_id="exp_cr",
            name="cr",
            version=1,
            description="",
            config_yaml="x: 1",
            config_hash="h",
            status="RUNNING",
        )
        assert cancel_experiment(session, "exp_cr") is True
        record = get_experiment(session, "exp_cr")
        assert record.status == "CANCEL_REQUESTED"

    def test_cancel_completed_noop(self, session):
        create_experiment(
            session,
            experiment_id="exp_cc",
            name="cc",
            version=1,
            description="",
            config_yaml="x: 1",
            config_hash="h",
            status="COMPLETED",
        )
        assert cancel_experiment(session, "exp_cc") is False

    def test_runs(self, session):
        create_experiment(
            session,
            experiment_id="exp_runs",
            name="runs",
            version=1,
            description="",
            config_yaml="x: 1",
            config_hash="h",
        )
        run = RunRecord(
            run_id="exp_runs/run-0",
            experiment_id="exp_runs",
            run_index=0,
            seed=42,
            status="QUEUED",
        )
        session.add(run)
        session.commit()
        runs = get_runs(session, "exp_runs")
        assert len(runs) == 1
        assert runs[0].seed == 42


class TestQueue:
    def test_enqueue_and_claim(self, redis_client):
        r = redis_client
        jobs = enqueue_experiment(r, "exp_q", "config: true", "hash", 2)
        assert len(jobs) == 2
        payload = claim_job(r, "worker-1", timeout=1)
        assert payload is not None
        assert payload.experiment_id == "exp_q"
        assert payload.worker_id == "worker-1"

    def test_claim_empty_queue(self, redis_client):
        payload = claim_job(redis_client, "worker-1", timeout=1)
        assert payload is None

    def test_complete_job(self, redis_client):
        r = redis_client
        enqueue_experiment(r, "exp_comp", "c: 1", "h", 1)
        payload = claim_job(r, "w-1", timeout=1)
        assert payload is not None
        complete_job(r, payload.run_id, "COMPLETED", "/path/to/artifacts")
        status = get_job_status(r, payload.run_id)
        assert status == "COMPLETED"

    def test_requeue_stuck_jobs(self, redis_client):
        r = redis_client
        enqueue_experiment(r, "exp_stuck", "c: 1", "h", 1)
        payload = claim_job(r, "w-1", timeout=1)
        assert payload is not None
        r.hset(
            f"resiliencelab:job:{payload.run_id}",
            "payload",
            JobPayload(
                experiment_id="exp_stuck",
                run_id=payload.run_id,
                run_index=0,
                seed=0,
                config_yaml="c: 1",
                config_hash="h",
                worker_id="w-1",
                created_at=time.time(),
                claimed_at=time.time() - 700,
            ).to_json(),
        )
        count = requeue_stuck_jobs(r, max_age_seconds=600)
        assert count == 1

    def test_job_payload_roundtrip(self):
        payload = JobPayload(
            experiment_id="exp_rt",
            run_id="exp_rt/run-0",
            run_index=0,
            seed=42,
            config_yaml="test: true",
            config_hash="abc",
        )
        data = payload.to_json()
        restored = JobPayload.from_json(data)
        assert restored.experiment_id == payload.experiment_id
        assert restored.seed == payload.seed
        assert restored.config_yaml == payload.config_yaml
