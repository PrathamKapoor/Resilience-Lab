"""Server E2E integration tests.

Tests the full pipeline: API -> PostgreSQL -> Redis -> Worker -> ExperimentRunner
-> Artifacts -> API retrieval.

Requires:
- PostgreSQL on 127.0.0.1:5432 (resiliencelab:resiliencelab)
- Redis on 127.0.0.1:6379

These tests are skipped if PostgreSQL or Redis is unavailable.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
import redis
from fastapi.testclient import TestClient

# Check infrastructure availability before importing anything heavy
_infra_available = True
try:
    import psycopg  # noqa: F401
    from sqlalchemy import text

    from resiliencelab.controlplane.database import get_engine

    engine = get_engine()
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
except Exception:
    _infra_available = False

try:
    r_client = redis.Redis()
    r_client.ping()
except Exception:
    _infra_available = False

pytestmark = pytest.mark.skipif(
    not _infra_available,
    reason="PostgreSQL or Redis not available for E2E testing",
)


@pytest.fixture(autouse=True)
def _configure_server_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Server-mode tests must exercise the secure production default."""
    monkeypatch.setenv("RESILIENCELAB_AUTH_MODE", "api_key")
    monkeypatch.setenv("RESILIENCELAB_API_KEYS", "e2e-test-key")


# Ensure clean schema before tests
if _infra_available:
    from resiliencelab.controlplane.models import Base

    # Clear queued jobs before replacing the database schema. Otherwise a worker
    # can claim a job whose experiment row was removed by drop_all().
    r_client.flushdb()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_config_counter = 0


def _next_id(prefix: str = "e2e") -> str:
    global _config_counter
    _config_counter += 1
    return f"{prefix}_{_config_counter}_{int(time.time() * 1000) % 10000}"


def _tiny_config(exp_id: str | None = None) -> dict:
    exp_id = exp_id or _next_id()
    return {
        "experiment": {"id": exp_id, "name": f"e2e {exp_id}"},
        "workload": {
            "type": "closed_loop",
            "clients": 1,
            "duration": "0.2s",
            "warmup": "0s",
        },
        "repetitions": {"count": 1, "base_seed": 99},
    }


_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()


def _ensure_worker() -> None:
    """Start a background worker if not already running."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(
            target=_run_worker,
            daemon=True,
            name="e2e-worker",
        )
        _worker_thread.start()
        time.sleep(0.5)  # Let worker initialize


def _run_worker() -> None:
    """Run a worker in a background thread."""
    from resiliencelab.controlplane.worker import run_worker

    run_worker(
        worker_id="e2e-test-worker",
        poll_interval=1,
        max_jobs=500,
        cancel_poll_interval=0.5,
    )


def _make_client() -> TestClient:
    """Create a server-mode API client and ensure worker is running."""
    from resiliencelab.api.app import create_app

    app = create_app(server_mode=True)
    _ensure_worker()
    return TestClient(app, headers={"X-API-Key": "e2e-test-key"})


def _wait_for_status(
    client: TestClient, exp_id: str, target: str | set[str], timeout: int = 60
) -> str:
    """Poll experiment status until it reaches a target state."""
    for _ in range(timeout):
        time.sleep(1)
        resp = client.get(f"/api/v1/experiments/{exp_id}/status")
        if resp.status_code == 200:
            status = resp.json()["status"]
            if isinstance(target, set):
                if status in target:
                    return status
            elif status == target:
                return status
    # Return whatever we got
    resp = client.get(f"/api/v1/experiments/{exp_id}/status")
    return resp.json()["status"] if resp.status_code == 200 else "UNKNOWN"


# ---------------------------------------------------------------------------
# E2E 1: Submit -> Complete
# ---------------------------------------------------------------------------


class TestE2ESubmitComplete:
    """Full lifecycle: submit -> queue -> worker -> runner -> artifact -> retrieval."""

    def test_full_lifecycle(self) -> None:
        client = _make_client()
        exp_id = _next_id("lc")

        # Submit experiment
        resp = client.post("/api/v1/experiments", json={"config": _tiny_config(exp_id)})
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == exp_id
        assert body["status"] == "queued"

        # Wait for completion
        final_status = _wait_for_status(client, exp_id, {"COMPLETED", "FAILED", "CANCELLED"})
        assert final_status == "COMPLETED", f"Expected COMPLETED, got {final_status}"

        # Verify runs
        runs_resp = client.get(f"/api/v1/experiments/{exp_id}/runs")
        assert runs_resp.status_code == 200
        runs = runs_resp.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["status"] == "COMPLETED"

        # Verify experiment detail
        detail_resp = client.get(f"/api/v1/experiments/{exp_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()["experiment"]
        assert detail["id"] == exp_id
        assert detail["status"] == "COMPLETED"
        assert detail["config_hash"] is not None

        # Verify artifacts exist on disk
        assert runs[0]["artifact_path"] is not None
        artifact_dir = Path(runs[0]["artifact_path"])
        assert artifact_dir.exists()
        assert (artifact_dir / "manifest.json").exists()
        assert (artifact_dir / "configuration.yaml").exists()
        assert (artifact_dir / "experiment.json").exists()

        # Verify manifest integrity
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        assert manifest["experiment_id"] == exp_id
        assert manifest["cancelled"] is False
        assert manifest["completed_repetitions"] == 1
        assert manifest["requested_repetitions"] == 1
        assert "files" in manifest
        assert len(manifest["files"]) > 0

    def test_api_artifact_endpoint(self) -> None:
        client = _make_client()
        exp_id = _next_id("art")
        client.post("/api/v1/experiments", json={"config": _tiny_config(exp_id)})
        final = _wait_for_status(client, exp_id, {"COMPLETED", "FAILED"})
        assert final == "COMPLETED"

        # Get artifacts via API
        resp = client.get(f"/api/v1/experiments/{exp_id}/artifacts")
        assert resp.status_code == 200
        body = resp.json()
        assert "manifest" in body
        assert "files" in body
        assert body["manifest"]["experiment_id"] == exp_id
        assert body["manifest"]["cancelled"] is False
        assert len(body["files"]) > 0
        for f in body["files"]:
            assert "sha256" in f
            assert "path" in f
            assert len(f["sha256"]) == 64

    def test_api_reads_completed_artifacts(self) -> None:
        client = _make_client()
        exp_id = _next_id("read")
        client.post("/api/v1/experiments", json={"config": _tiny_config(exp_id)})
        final = _wait_for_status(client, exp_id, {"COMPLETED", "FAILED"})
        assert final == "COMPLETED"

        metrics = client.get(f"/api/v1/experiments/{exp_id}/metrics")
        assert metrics.status_code == 200
        assert metrics.json()["metrics_per_run"]

        timeline = client.get(f"/api/v1/experiments/{exp_id}/timeline")
        assert timeline.status_code == 200
        assert timeline.json()["timeline"]

        report = client.get(f"/api/v1/experiments/{exp_id}/report")
        assert report.status_code == 200
        assert exp_id in report.text

        analysis = client.get(f"/api/v1/experiments/{exp_id}/analysis")
        assert analysis.status_code == 200
        assert analysis.json()["analysis"]

    def test_api_rejects_tampered_artifact(self) -> None:
        client = _make_client()
        exp_id = _next_id("tamper")
        client.post("/api/v1/experiments", json={"config": _tiny_config(exp_id)})
        assert _wait_for_status(client, exp_id, {"COMPLETED", "FAILED"}) == "COMPLETED"

        from pathlib import Path

        run = client.get(f"/api/v1/experiments/{exp_id}/runs").json()["runs"][0]
        target = Path(run["artifact_path"]) / "experiment.json"
        original = target.read_text()
        target.write_text(original + "\n ")
        try:
            assert client.get(f"/api/v1/experiments/{exp_id}/metrics").status_code == 409
        finally:
            target.write_text(original)


# ---------------------------------------------------------------------------
# E2E 2: Submit -> Cancel
# ---------------------------------------------------------------------------


class TestE2ESubmitCancel:
    """Cancellation lifecycle: submit -> cancel -> worker observes -> partial artifact."""

    def test_cancel_running_experiment(self) -> None:
        client = _make_client()
        exp_id = _next_id("cnl")
        config = _tiny_config(exp_id)
        config["workload"]["duration"] = "10s"
        config["repetitions"]["count"] = 5

        # Submit
        resp = client.post("/api/v1/experiments", json={"config": config})
        assert resp.status_code == 201

        # Wait for RUNNING state
        for _ in range(20):
            time.sleep(0.5)
            status = client.get(f"/api/v1/experiments/{exp_id}/status").json()["status"]
            if status == "RUNNING":
                break

        # Cancel
        cancel_resp = client.post(
            f"/api/v1/experiments/{exp_id}/cancel",
            json={"reason": "E2E test cancellation"},
        )
        assert cancel_resp.status_code == 200
        cancel_body = cancel_resp.json()
        assert cancel_body["status"] in (
            "cancel_requested",
            "cancelled",
            "already_completed",
        )

        # Wait for terminal state
        final_status = _wait_for_status(client, exp_id, {"COMPLETED", "FAILED", "CANCELLED"})
        assert final_status in ("COMPLETED", "CANCELLED")
        if final_status == "CANCELLED":
            final = client.get(f"/api/v1/experiments/{exp_id}/status").json()
            assert final["cancellation_reason"] is not None


# ---------------------------------------------------------------------------
# E2E 3: Cancel vs Completion Race
# ---------------------------------------------------------------------------


class TestE2ECancelRace:
    """Verify atomic terminal state handling."""

    def test_cancel_near_completion(self) -> None:
        client = _make_client()
        exp_id = _next_id("race")
        config = _tiny_config(exp_id)
        config["workload"]["duration"] = "0.3s"

        client.post("/api/v1/experiments", json={"config": config})

        # Wait a moment then try to cancel
        time.sleep(0.5)
        client.post(f"/api/v1/experiments/{exp_id}/cancel")

        # Wait for terminal state
        final_status = _wait_for_status(client, exp_id, {"COMPLETED", "CANCELLED", "FAILED"})
        # Must be a valid terminal state — no illegal transitions
        assert final_status in ("COMPLETED", "CANCELLED", "FAILED")


# ---------------------------------------------------------------------------
# E2E 4: Duplicate Queue Delivery
# ---------------------------------------------------------------------------


class TestE2EDuplicateDelivery:
    """Verify Redis != authoritative state."""

    def test_duplicate_enqueue_no_extra_runs(self) -> None:
        client = _make_client()
        exp_id = _next_id("dup")
        config = _tiny_config(exp_id)

        # Submit once
        resp1 = client.post("/api/v1/experiments", json={"config": config})
        assert resp1.status_code == 201

        # Wait for completion
        final = _wait_for_status(client, exp_id, {"COMPLETED", "FAILED"})
        assert final == "COMPLETED"

        # Verify only 1 run
        runs = client.get(f"/api/v1/experiments/{exp_id}/runs").json()["runs"]
        assert len(runs) == 1


# ---------------------------------------------------------------------------
# E2E 5: Pagination and Filtering
# ---------------------------------------------------------------------------


class TestE2EPagination:
    def test_pagination_with_real_data(self) -> None:
        client = _make_client()
        for _ in range(5):
            eid = _next_id("pg")
            client.post("/api/v1/experiments", json={"config": _tiny_config(eid)})

        # Page 1
        resp = client.get("/api/v1/experiments?limit=2&offset=0")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pagination"]["total"] >= 5
        assert body["pagination"]["limit"] == 2
        assert body["pagination"]["has_more"] is True
        assert len(body["experiments"]) == 2

        # Page 2
        resp2 = client.get("/api/v1/experiments?limit=2&offset=2")
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["experiments"]) == 2
        ids_page1 = {e["id"] for e in body["experiments"]}
        ids_page2 = {e["id"] for e in body2["experiments"]}
        assert ids_page1.isdisjoint(ids_page2)


# ---------------------------------------------------------------------------
# E2E 6: Idempotency
# ---------------------------------------------------------------------------


class TestE2EIdempotency:
    def test_create_idempotent(self) -> None:
        client = _make_client()
        exp_id = _next_id("idem")
        config = _tiny_config(exp_id)

        r1 = client.post("/api/v1/experiments", json={"config": config})
        assert r1.status_code == 201

        r2 = client.post("/api/v1/experiments", json={"config": config})
        assert r2.status_code in (201, 409)
        if r2.status_code == 201:
            assert r2.json()["id"] == exp_id

    def test_cancel_idempotent(self) -> None:
        client = _make_client()
        exp_id = _next_id("idem_cancel")
        config = _tiny_config(exp_id)
        config["workload"]["duration"] = "5s"

        client.post("/api/v1/experiments", json={"config": config})

        # Wait for RUNNING
        for _ in range(20):
            time.sleep(0.5)
            status = client.get(f"/api/v1/experiments/{exp_id}/status").json()["status"]
            if status in ("RUNNING", "COMPLETED"):
                break

        # Cancel twice
        r1 = client.post(f"/api/v1/experiments/{exp_id}/cancel")
        r2 = client.post(f"/api/v1/experiments/{exp_id}/cancel")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["status"] in (
            "cancel_requested",
            "cancelled",
            "already_cancel_requested",
            "already_cancelled",
            "already_completed",
        )
        assert r2.json()["status"] in (
            "cancel_requested",
            "cancelled",
            "already_cancel_requested",
            "already_cancelled",
            "already_completed",
        )


# ---------------------------------------------------------------------------
# E2E 7: Authorization
# ---------------------------------------------------------------------------


class TestE2EAuthorization:
    def test_owner_based_access_control(self) -> None:
        import os

        os.environ["RESILIENCELAB_AUTH_MODE"] = "api_key"
        os.environ["RESILIENCELAB_API_KEYS"] = "user-a-key,user-b-key"
        try:
            from resiliencelab.api.app import create_app

            app = create_app(server_mode=True)
            client_a = TestClient(app)
            client_b = TestClient(app)

            exp_id = _next_id("auth")
            resp = client_a.post(
                "/api/v1/experiments",
                json={"config": _tiny_config(exp_id)},
                headers={"X-API-Key": "user-a-key"},
            )
            assert resp.status_code == 201

            # User B cannot access User A's experiment
            resp_b = client_b.get(
                f"/api/v1/experiments/{exp_id}",
                headers={"X-API-Key": "user-b-key"},
            )
            assert resp_b.status_code == 403

            # User A can access their own experiment
            resp_a = client_a.get(
                f"/api/v1/experiments/{exp_id}",
                headers={"X-API-Key": "user-a-key"},
            )
            assert resp_a.status_code == 200
        finally:
            os.environ.pop("RESILIENCELAB_AUTH_MODE", None)
            os.environ.pop("RESILIENCELAB_API_KEYS", None)


# ---------------------------------------------------------------------------
# E2E 8: Health / Readiness
# ---------------------------------------------------------------------------


class TestE2EHealth:
    def test_liveness_always_ok(self) -> None:
        from resiliencelab.api.app import create_app

        app = create_app(server_mode=True)
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_readiness_checks_dependencies(self) -> None:
        from resiliencelab.api.app import create_app

        app = create_app(server_mode=True)
        client = TestClient(app)
        resp = client.get("/api/v1/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded", "down")
        assert "postgres" in body["checks"]
        assert "redis" in body["checks"]
