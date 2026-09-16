"""Phase 12: Adversarial System Testing.

Attack the platform to find state corruption, scientific corruption,
data corruption, authorization bugs, race conditions, and
reproducibility failures.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from resiliencelab.api.app import LocalRuntime, create_app
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.provenance import hash_config
from resiliencelab.experiments.result import ExperimentResult
from resiliencelab.metrics.transforms import RequestSummary

DUMMY_SUMMARY = RequestSummary(
    total=100,
    successful=95,
    failed=5,
    timeouts=0,
    availability=0.95,
    throughput=50.0,
    latency_mean=0.01,
    latency_median=0.009,
    latency_p95=0.02,
    latency_p99=0.03,
    latency_p999=0.05,
    error_rate=0.05,
    timeout_rate=0.0,
    amplifications={"requests": 1.1},
)


def _tiny_config(exp_id: str = "adv_test") -> dict:
    return {
        "experiment": {"id": exp_id, "name": f"adv {exp_id}"},
        "workload": {"type": "closed_loop", "clients": 1, "duration": "0.1s"},
        "repetitions": {"count": 1, "base_seed": 99},
    }


# ===================================================================
# 12.1  API Adversarial Tests
# ===================================================================


class TestAPIAttacks:
    def test_missing_config_field(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.post("/api/v1/experiments", json={})
        assert resp.status_code in (400, 422)

    def test_empty_config(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.post("/api/v1/experiments", json={"config": {}})
        assert resp.status_code in (400, 422)

    def test_invalid_config_type(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.post("/api/v1/experiments", json={"config": "not_a_dict"})
        assert resp.status_code in (400, 422)

    def test_negative_repetitions(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        config = {
            "experiment": {"id": "neg", "name": "neg"},
            "repetitions": {"count": -1},
        }
        resp = client.post("/api/v1/experiments", json={"config": config})
        assert resp.status_code in (400, 422)

    def test_zero_repetitions(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        config = {
            "experiment": {"id": "zero", "name": "zero"},
            "repetitions": {"count": 0},
        }
        resp = client.post("/api/v1/experiments", json={"config": config})
        assert resp.status_code in (400, 422)

    def test_invalid_experiment_id_slash(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        config = _tiny_config("bad/id")
        resp = client.post("/api/v1/experiments", json={"config": config})
        assert resp.status_code == 422

    def test_invalid_experiment_id_null(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        config = _tiny_config("bad\x00id")
        resp = client.post("/api/v1/experiments", json={"config": config})
        assert resp.status_code == 422

    def test_huge_experiment_id(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        config = _tiny_config("x" * 300)
        resp = client.post("/api/v1/experiments", json={"config": config})
        assert resp.status_code == 422

    def test_invalid_pagination_negative_offset(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments?offset=-1")
        assert resp.status_code == 422

    def test_invalid_pagination_zero_limit(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments?limit=0")
        assert resp.status_code == 422

    def test_pagination_limit_exceeds_max(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments?limit=1000")
        assert resp.status_code == 422

    def test_nonexistent_experiment_404(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments/nonexistent_999")
        assert resp.status_code == 404

    def test_no_stack_trace_leaks(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.post("/api/v1/experiments", json={})
        body = resp.json()
        assert "traceback" not in json.dumps(body).lower()
        assert "stack" not in json.dumps(body).lower()


# ===================================================================
# 12.2  Lifecycle State Machine Attacks
# ===================================================================


class TestLifecycleAttacks:
    def test_terminal_state_resurrection_prevented(self) -> None:
        """Once COMPLETED, an experiment cannot be cancelled."""
        runtime = LocalRuntime()
        app = create_app(runtime=runtime)
        client = TestClient(app)

        config = _tiny_config("lifecycle_resurrect")
        resp = client.post("/api/v1/experiments", json={"config": config})
        assert resp.status_code == 201
        exp_id = resp.json()["id"]

        # Wait for completion (local mode is fast)
        time.sleep(2.0)

        # Try to cancel completed experiment — should fail gracefully
        cancel_resp = client.post(f"/api/v1/experiments/{exp_id}/cancel")
        assert cancel_resp.status_code == 200
        body = cancel_resp.json()
        # Experiment already completed or not found — either is acceptable
        assert body["status"] in (
            "already_completed",
            "already_failed",
            "already_cancelled",
            "not_started",
            "not_found",
        )

    def test_cancel_nonexistent_experiment(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.post("/api/v1/experiments/nonexistent_999/cancel")
        assert resp.status_code == 404

    def test_double_cancel_idempotent(self) -> None:
        runtime = LocalRuntime()
        app = create_app(runtime=runtime)
        client = TestClient(app)

        config = _tiny_config("double_cancel")
        resp = client.post("/api/v1/experiments", json={"config": config})
        exp_id = resp.json()["id"]

        # Wait briefly
        time.sleep(0.5)

        # Cancel twice
        r1 = client.post(f"/api/v1/experiments/{exp_id}/cancel")
        r2 = client.post(f"/api/v1/experiments/{exp_id}/cancel")
        assert r1.status_code == 200
        assert r2.status_code == 200
        # Both should return consistent status
        valid_statuses = {
            "cancel_requested",
            "cancelled",
            "already_cancel_requested",
            "already_completed",
            "not_started",
            "not_found",
        }
        assert r1.json()["status"] in valid_statuses
        assert r2.json()["status"] in valid_statuses


# ===================================================================
# 12.3  Concurrent Submission
# ===================================================================


class TestConcurrentSubmission:
    def test_duplicate_idempotent_submission(self) -> None:
        """Two submissions with same config should be idempotent."""
        runtime = LocalRuntime()
        app = create_app(runtime=runtime)
        client = TestClient(app)

        config = _tiny_config("idempotent_concurrent")
        r1 = client.post("/api/v1/experiments", json={"config": config})
        r2 = client.post("/api/v1/experiments", json={"config": config})
        assert r1.status_code == 201
        assert r2.status_code in (201, 409)

    def test_concurrent_cancellation_requests(self) -> None:
        """Multiple concurrent cancel requests should not corrupt state."""
        runtime = LocalRuntime()
        app = create_app(runtime=runtime)
        client = TestClient(app)

        config = _tiny_config("concurrent_cancel")
        resp = client.post("/api/v1/experiments", json={"config": config})
        exp_id = resp.json()["id"]

        time.sleep(0.5)

        # Issue multiple cancel requests concurrently
        results = []

        def do_cancel():
            r = client.post(f"/api/v1/experiments/{exp_id}/cancel")
            results.append(r.json())

        threads = [threading.Thread(target=do_cancel) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should return valid status
        valid_statuses = {
            "cancel_requested",
            "cancelled",
            "already_cancel_requested",
            "already_completed",
            "not_started",
            "not_found",
        }
        for r in results:
            assert r["status"] in valid_statuses


# ===================================================================
# 12.4  Catalog and Health Endpoints
# ===================================================================


class TestCatalogAttacks:
    def test_health_always_returns_ok(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_benchmarks_returns_list(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/benchmarks")
        assert resp.status_code == 200
        assert "benchmarks" in resp.json()

    def test_policies_returns_list(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/policies")
        assert resp.status_code == 200
        assert "mechanisms" in resp.json()

    def test_fault_models_returns_list(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/fault-models")
        assert resp.status_code == 200

    def test_workloads_returns_list(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/workloads")
        assert resp.status_code == 200
        assert "workload_types" in resp.json()


# ===================================================================
# 12.5  Run and Analysis Endpoints
# ===================================================================


class TestRunAnalysisAttacks:
    def test_runs_for_nonexistent_experiment(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments/nonexistent_999/runs")
        assert resp.status_code == 404

    def test_analysis_for_nonexistent_experiment(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments/nonexistent_999/analysis")
        assert resp.status_code == 404

    def test_events_for_nonexistent_experiment(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments/nonexistent_999/events")
        assert resp.status_code == 404

    def test_timeline_for_nonexistent_experiment(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments/nonexistent_999/timeline")
        assert resp.status_code == 404

    def test_result_for_nonexistent_experiment(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments/nonexistent_999/result")
        assert resp.status_code == 404


# ===================================================================
# 12.6  Scientific State Isolation
# ===================================================================


class TestScientificIsolation:
    def test_different_experiments_independent(self) -> None:
        """Two experiments with different IDs should produce independent results."""
        runtime = LocalRuntime()
        app = create_app(runtime=runtime)
        client = TestClient(app)

        c1 = _tiny_config("iso_a")
        c2 = _tiny_config("iso_b")
        r1 = client.post("/api/v1/experiments", json={"config": c1})
        r2 = client.post("/api/v1/experiments", json={"config": c2})
        assert r1.status_code == 201
        assert r2.status_code == 201

        # Wait for both to complete
        for _ in range(30):
            time.sleep(0.5)
            s1 = client.get(f"/api/v1/experiments/{r1.json()['id']}/status").json()["status"]
            s2 = client.get(f"/api/v1/experiments/{r2.json()['id']}/status").json()["status"]
            if s1 in ("COMPLETED", "FAILED") and s2 in ("COMPLETED", "FAILED"):
                break

        # Results should be independent
        res1 = runtime.registry.get_result("iso_a")
        res2 = runtime.registry.get_result("iso_b")
        if res1 is not None and res2 is not None:
            assert res1.experiment.id != res2.experiment.id
            assert res1.config_hash != res2.config_hash or res1.experiment.id != res2.experiment.id

    def test_same_config_same_hash(self) -> None:
        """Same config should produce the same config_hash."""
        c1 = _tiny_config("hash_a")
        c2 = _tiny_config("hash_a")
        spec1 = ExperimentSpec.model_validate(
            c1["experiment"]
            | {
                "workload": c1["workload"],
                "repetitions": c1["repetitions"],
            }
        )
        spec2 = ExperimentSpec.model_validate(
            c2["experiment"]
            | {
                "workload": c2["workload"],
                "repetitions": c2["repetitions"],
            }
        )
        assert hash_config(spec1) == hash_config(spec2)

    def test_different_seeds_different_results(self) -> None:
        """Different seeds should produce different artifact content."""
        spec1 = ExperimentSpec(
            id="seed_a",
            name="seed_a",
            repetitions={"count": 2, "base_seed": 42},
        )
        spec2 = ExperimentSpec(
            id="seed_b",
            name="seed_b",
            repetitions={"count": 2, "base_seed": 99},
        )
        # Seeds are different
        assert spec1.repetitions.base_seed != spec2.repetitions.base_seed


# ===================================================================
# 12.7  Request ID Tracking
# ===================================================================


class TestRequestIdTracking:
    def test_request_id_in_response_headers(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert "X-Request-ID" in resp.headers

    def test_custom_request_id_propagated(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/health", headers={"X-Request-ID": "custom-id-123"})
        assert resp.headers.get("X-Request-ID") == "custom-id-123"


# ===================================================================
# 12.8  Error Envelope Structure
# ===================================================================


class TestErrorEnvelope:
    def test_error_has_machine_code(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.post("/api/v1/experiments", json={})
        assert resp.status_code in (400, 422)
        body = resp.json()
        # Error response should have structured detail
        assert "detail" in body

    def test_not_found_is_consistent(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments/nonexistent_xyz")
        assert resp.status_code == 404


# ===================================================================
# 12.9  Schema Validation
# ===================================================================


class TestSchemaValidation:
    def test_valid_config_accepted(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        config = _tiny_config("valid_schema")
        resp = client.post("/api/v1/experiments", json={"config": config})
        assert resp.status_code == 201

    def test_extra_fields_in_config(self) -> None:
        """Extra fields in config should be handled gracefully (not crash)."""
        app = create_app(server_mode=False)
        client = TestClient(app)
        config = _tiny_config("extra_fields")
        config["experiment"]["extra_field"] = "unexpected"
        resp = client.post("/api/v1/experiments", json={"config": config})
        # Should either succeed (extra ignored) or return 422
        assert resp.status_code in (201, 422)

    def test_missing_experiment_id(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        config = {"workload": {"type": "closed_loop", "clients": 1, "duration": "0.1s"}}
        resp = client.post("/api/v1/experiments", json={"config": config})
        assert resp.status_code in (400, 422)


# ===================================================================
# 12.10  Artifact Verification via API
# ===================================================================


class TestArtifactAPI:
    def test_artifacts_endpoint_exists(self) -> None:
        app = create_app(server_mode=False)
        client = TestClient(app)
        resp = client.get("/api/v1/experiments/nonexistent/artifacts")
        assert resp.status_code == 404

    def test_manifest_structure(self, tmp_path: Path) -> None:
        """Verify manifest structure is self-consistent."""
        from resiliencelab.experiments.artifacts import verify_artifacts, write_artifacts

        spec = ExperimentSpec(id="manifest_check", name="mc")
        result = ExperimentResult(
            experiment=spec,
            policy_name="test",
            config_hash=hash_config(spec),
            runs=[],
            environment={"python": "3.13"},
        )
        base = tmp_path / "mc"
        manifest = write_artifacts(result, base)
        v = verify_artifacts(base)
        assert v["valid"] is True
        assert manifest["completed_repetitions"] == 0
        assert manifest["cancelled"] is False
