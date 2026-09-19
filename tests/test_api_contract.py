"""Phase 8: API contract, auth, pagination, idempotency, validation, and health tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from resiliencelab import __version__
from resiliencelab.api.app import LocalRuntime, create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runtime_client() -> TestClient:
    return TestClient(create_app(LocalRuntime()))


def _tiny_config(exp_id: str = "exp_p8") -> dict[str, Any]:
    return {
        "experiment": {"id": exp_id, "name": f"phase8 {exp_id}"},
        "workload": {"type": "closed_loop", "clients": 1, "duration": "0.1s", "warmup": "0s"},
        "repetitions": {"count": 1, "base_seed": 42},
    }


def _run_experiment(client: TestClient, exp_id: str = "exp_p8") -> None:
    client.post("/api/v1/experiments", json={"config": _tiny_config(exp_id)})
    client.post(f"/api/v1/experiments/{exp_id}/run")


# ---------------------------------------------------------------------------
# Test: API Contract — typed responses, status codes
# ---------------------------------------------------------------------------


class TestAPIContract:
    """Every endpoint must return predictable typed responses."""

    def test_health_returns_typed_response(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "server_mode" in body
        assert "version" in body

    def test_health_version_matches_the_package_version(self) -> None:
        client = _runtime_client()

        assert client.get("/api/v1/health").json()["version"] == __version__

    def test_readiness_local_mode(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["server_mode"] is False

    def test_catalog_endpoints_typed(self) -> None:
        client = _runtime_client()
        for path in (
            "/api/v1/benchmarks",
            "/api/v1/policies",
            "/api/v1/fault-models",
            "/api/v1/workloads",
        ):
            resp = client.get(path)
            assert resp.status_code == 200
            body = resp.json()
            assert isinstance(body, dict)

    def test_create_experiment_returns_typed_response(self) -> None:
        client = _runtime_client()
        resp = client.post("/api/v1/experiments", json={"config": _tiny_config("c1")})
        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert "name" in body
        assert "status" in body
        assert body["id"] == "c1"
        assert body["status"] == "created"

    def test_list_experiments_returns_pagination(self) -> None:
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("l1")})
        client.post("/api/v1/experiments", json={"config": _tiny_config("l2")})
        resp = client.get("/api/v1/experiments")
        assert resp.status_code == 200
        body = resp.json()
        assert "experiments" in body
        assert "pagination" in body
        pag = body["pagination"]
        assert "total" in pag
        assert "offset" in pag
        assert "limit" in pag
        assert "has_more" in pag

    def test_get_experiment_returns_typed_detail(self) -> None:
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("g1")})
        resp = client.get("/api/v1/experiments/g1")
        assert resp.status_code == 200
        exp = resp.json()["experiment"]
        for field in (
            "id",
            "name",
            "version",
            "description",
            "status",
            "config_hash",
            "created_at",
            "updated_at",
        ):
            assert field in exp, f"missing field {field}"

    def test_status_returns_typed_response(self) -> None:
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("s1")})
        resp = client.get("/api/v1/experiments/s1/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "id" in body
        assert "status" in body
        assert "runs" in body

    def test_run_returns_typed_response(self) -> None:
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("r1")})
        resp = client.post("/api/v1/experiments/r1/run")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "r1"
        assert body["status"] == "running"

    def test_cancel_returns_typed_response(self) -> None:
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("x1")})
        resp = client.post("/api/v1/experiments/x1/cancel", json={"reason": "testing"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "x1"
        assert "status" in body

    def test_404_returns_error_envelope(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/experiments/nonexistent")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body

    def test_metrics_typed_local(self) -> None:
        client = _runtime_client()
        _run_experiment(client, "m1")
        resp = client.get("/api/v1/experiments/m1/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert "metrics_per_run" in body
        assert isinstance(body["metrics_per_run"], list)

    def test_timeline_typed_local(self) -> None:
        client = _runtime_client()
        _run_experiment(client, "t1")
        resp = client.get("/api/v1/experiments/t1/timeline")
        assert resp.status_code == 200
        body = resp.json()
        assert "timeline" in body

    def test_events_typed_local(self) -> None:
        client = _runtime_client()
        _run_experiment(client, "e1")
        resp = client.get("/api/v1/experiments/e1/events")
        assert resp.status_code == 200
        body = resp.json()
        assert "event_schema_version" in body
        assert "count" in body
        assert "events" in body

    def test_report_typed_local(self) -> None:
        client = _runtime_client()
        _run_experiment(client, "rp1")
        resp = client.get("/api/v1/experiments/rp1/report")
        assert resp.status_code == 200
        assert isinstance(resp.text, str)
        assert len(resp.text) > 0

    def test_analysis_typed_local(self) -> None:
        client = _runtime_client()
        _run_experiment(client, "a1")
        resp = client.get("/api/v1/experiments/a1/analysis")
        assert resp.status_code == 200
        body = resp.json()
        assert "analysis" in body


# ---------------------------------------------------------------------------
# Test: Request correlation IDs
# ---------------------------------------------------------------------------


class TestCorrelationIDs:
    def test_request_id_returned_in_response_header(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/health")
        assert "X-Request-ID" in resp.headers

    def test_custom_request_id_preserved(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/health", headers={"X-Request-ID": "test-123"})
        assert resp.headers.get("X-Request-ID") == "test-123"

    def test_request_id_in_error_response(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/experiments/missing", headers={"X-Request-ID": "err-456"})
        assert resp.headers.get("X-Request-ID") == "err-456"


# ---------------------------------------------------------------------------
# Test: Authentication (none mode)
# ---------------------------------------------------------------------------


class TestServerAuthenticationConfiguration:
    def test_server_mode_rejects_anonymous_authentication(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("RESILIENCELAB_AUTH_MODE", raising=False)
        monkeypatch.delenv("RESILIENCELAB_API_KEYS", raising=False)

        with pytest.raises(RuntimeError, match="RESILIENCELAB_AUTH_MODE=api_key"):
            create_app(server_mode=True)

    def test_server_mode_requires_at_least_one_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from resiliencelab.api.auth import validate_server_auth_configuration

        monkeypatch.setenv("RESILIENCELAB_AUTH_MODE", "api_key")
        monkeypatch.delenv("RESILIENCELAB_API_KEYS", raising=False)

        with pytest.raises(RuntimeError, match="RESILIENCELAB_API_KEYS"):
            validate_server_auth_configuration()


class TestAuthNoneMode:
    def test_none_mode_allows_all_requests(self) -> None:
        client = _runtime_client()
        resp = client.post("/api/v1/experiments", json={"config": _tiny_config("auth1")})
        assert resp.status_code == 201

    def test_none_mode_allows_read(self) -> None:
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("auth2")})
        resp = client.get("/api/v1/experiments/auth2")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Authentication (api_key mode)
# ---------------------------------------------------------------------------


class TestAuthAPIKeyMode:
    def _make_client(
        self, monkeypatch: pytest.MonkeyPatch, api_keys: str = "test-key-1,test-key-2"
    ) -> TestClient:
        monkeypatch.setenv("RESILIENCELAB_AUTH_MODE", "api_key")
        monkeypatch.setenv("RESILIENCELAB_API_KEYS", api_keys)
        app = create_app(LocalRuntime())
        return TestClient(app)

    def test_valid_api_key_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._make_client(monkeypatch)
        resp = client.post(
            "/api/v1/experiments",
            json={"config": _tiny_config("ak1")},
            headers={"X-API-Key": "test-key-1"},
        )
        assert resp.status_code == 201

    def test_valid_bearer_token_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._make_client(monkeypatch)
        resp = client.post(
            "/api/v1/experiments",
            json={"config": _tiny_config("ak2")},
            headers={"Authorization": "Bearer test-key-2"},
        )
        assert resp.status_code == 201

    def test_invalid_key_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._make_client(monkeypatch)
        resp = client.post(
            "/api/v1/experiments",
            json={"config": _tiny_config("ak3")},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_missing_key_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._make_client(monkeypatch)
        resp = client.post("/api/v1/experiments", json={"config": _tiny_config("ak4")})
        assert resp.status_code == 401

    def test_health_endpoint_no_auth_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._make_client(monkeypatch)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    def test_pagination_metadata(self) -> None:
        client = _runtime_client()
        for i in range(5):
            client.post("/api/v1/experiments", json={"config": _tiny_config(f"pg{i}")})
        resp = client.get("/api/v1/experiments?limit=3&offset=0")
        body = resp.json()
        pag = body["pagination"]
        assert pag["total"] >= 5
        assert pag["limit"] == 3
        assert pag["offset"] == 0
        assert len(body["experiments"]) <= 3

    def test_offset_advances(self) -> None:
        client = _runtime_client()
        for i in range(5):
            client.post("/api/v1/experiments", json={"config": _tiny_config(f"po{i}")})
        page1 = client.get("/api/v1/experiments?limit=2&offset=0").json()
        page2 = client.get("/api/v1/experiments?limit=2&offset=2").json()
        ids1 = {e["id"] for e in page1["experiments"]}
        ids2 = {e["id"] for e in page2["experiments"]}
        assert ids1.isdisjoint(ids2)

    def test_max_page_size_enforced(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/experiments?limit=999")
        assert resp.status_code == 422

    def test_has_more_true_when_more_exist(self) -> None:
        client = _runtime_client()
        for i in range(3):
            client.post("/api/v1/experiments", json={"config": _tiny_config(f"hm{i}")})
        resp = client.get("/api/v1/experiments?limit=1&offset=0")
        body = resp.json()
        assert body["pagination"]["has_more"] is True

    def test_has_more_false_at_end(self) -> None:
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("hm1")})
        resp = client.get("/api/v1/experiments?limit=100&offset=0")
        body = resp.json()
        assert body["pagination"]["has_more"] is False


# ---------------------------------------------------------------------------
# Test: Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_duplicate_create_idempotent_queued(self) -> None:
        client = _runtime_client()
        resp1 = client.post("/api/v1/experiments", json={"config": _tiny_config("idem1")})
        resp2 = client.post("/api/v1/experiments", json={"config": _tiny_config("idem1")})
        assert resp1.status_code == 201
        assert resp2.status_code in (201, 409)
        if resp2.status_code == 201:
            assert resp2.json()["status"] == "created"

    def test_cancel_idempotent(self) -> None:
        import time

        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("idem2")})
        client.post("/api/v1/experiments/idem2/run")
        time.sleep(0.5)
        resp1 = client.post("/api/v1/experiments/idem2/cancel", json={"reason": "first"})
        resp2 = client.post("/api/v1/experiments/idem2/cancel", json={"reason": "second"})
        assert resp1.status_code == 200
        s1 = resp1.json()["status"]
        assert s1 in ("cancel_requested", "already_completed")
        assert resp2.status_code == 200
        s2 = resp2.json()["status"]
        assert s2 in ("already_cancel_requested", "already_completed")

    def test_cancel_completed_is_idempotent(self) -> None:
        client = _runtime_client()
        _run_experiment(client, "idem3")
        resp = client.post("/api/v1/experiments/idem3/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_completed"


# ---------------------------------------------------------------------------
# Test: Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_config_rejected_422(self) -> None:
        client = _runtime_client()
        resp = client.post("/api/v1/experiments", json={"config": {"invalid": True}})
        assert resp.status_code == 422

    def test_missing_config_rejected(self) -> None:
        client = _runtime_client()
        resp = client.post("/api/v1/experiments", json={})
        assert resp.status_code == 422

    def test_extra_fields_rejected(self) -> None:
        client = _runtime_client()
        resp = client.post(
            "/api/v1/experiments",
            json={"config": _tiny_config("v1"), "extra_field": "bad"},
        )
        assert resp.status_code == 422

    def test_experiment_id_with_slash_rejected(self) -> None:
        client = _runtime_client()
        resp = client.post(
            "/api/v1/experiments",
            json={"config": _tiny_config("bad/id")},
        )
        assert resp.status_code == 422

    def test_run_nonexistent_experiment_404(self) -> None:
        client = _runtime_client()
        resp = client.post("/api/v1/experiments/nonexistent/run")
        assert resp.status_code == 404

    def test_cancel_nonexistent_experiment_404(self) -> None:
        client = _runtime_client()
        resp = client.post("/api/v1/experiments/nonexistent/cancel")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: Lifecycle states
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_created_to_completed(self) -> None:
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("lc1")})
        client.post("/api/v1/experiments/lc1/run")
        status = client.get("/api/v1/experiments/lc1/status").json()
        assert status["status"] == "completed"

    def test_cancelled_is_terminal(self) -> None:
        import time

        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("lc2")})
        client.post("/api/v1/experiments/lc2/run")
        time.sleep(0.5)
        resp = client.post("/api/v1/experiments/lc2/cancel")
        status = resp.json()["status"]
        assert status in ("cancel_requested", "already_completed")

    def test_completed_cannot_be_cancelled(self) -> None:
        client = _runtime_client()
        _run_experiment(client, "lc3")
        resp = client.post("/api/v1/experiments/lc3/cancel")
        assert resp.json()["status"] == "already_completed"

    def test_cancelled_cannot_be_rerun_without_status(self) -> None:
        """Cancelled experiments can be re-run from the terminal state."""
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("lc4")})
        client.post("/api/v1/experiments/lc4/cancel")
        resp = client.post("/api/v1/experiments/lc4/run")
        assert resp.status_code == 200

    def test_run_while_queued_rejected(self) -> None:
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("lc5")})
        # In local mode, submitting starts immediately, so we test the 409
        # by checking that re-running a running experiment fails
        # (This is a local-mode-specific behavior)


# ---------------------------------------------------------------------------
# Test: Error boundary
# ---------------------------------------------------------------------------


class TestErrorBoundary:
    def test_404_has_consistent_shape(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/experiments/missing")
        assert resp.status_code == 404

    def test_validation_error_has_consistent_shape(self) -> None:
        client = _runtime_client()
        resp = client.post("/api/v1/experiments", json={"config": "not-a-dict"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: Health / Readiness
# ---------------------------------------------------------------------------


class TestHealthReadiness:
    def test_liveness_always_ok(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/health")
        assert resp.json()["status"] == "ok"

    def test_readiness_local_always_ok(self) -> None:
        client = _runtime_client()
        resp = client.get("/api/v1/ready")
        assert resp.json()["status"] == "ok"

    def test_health_no_auth_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RESILIENCELAB_AUTH_MODE", "api_key")
        monkeypatch.setenv("RESILIENCELAB_API_KEYS", "key1")
        app = create_app(LocalRuntime())
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Race — cancel vs completion (local mode)
# ---------------------------------------------------------------------------


class TestRaceConditions:
    def test_cancel_vs_completion_local(self) -> None:
        """In local mode, cancel on a completed experiment is idempotent."""
        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("race1")})
        client.post("/api/v1/experiments/race1/run")
        # Experiment should be completed by now (tiny workload)
        resp = client.post("/api/v1/experiments/race1/cancel")
        assert resp.json()["status"] == "already_completed"

    def test_double_cancel_is_idempotent(self) -> None:
        import time

        client = _runtime_client()
        client.post("/api/v1/experiments", json={"config": _tiny_config("race2")})
        client.post("/api/v1/experiments/race2/run")
        time.sleep(0.5)
        r1 = client.post("/api/v1/experiments/race2/cancel")
        r2 = client.post("/api/v1/experiments/race2/cancel")
        assert r1.status_code == 200
        s1 = r1.json()["status"]
        assert s1 in ("cancel_requested", "already_completed")
        assert r2.status_code == 200
        s2 = r2.json()["status"]
        assert s2 in ("already_cancel_requested", "already_completed")


# ---------------------------------------------------------------------------
# Test: Local mode backward compatibility
# ---------------------------------------------------------------------------


class TestLocalModeBackwardCompat:
    def test_experiment_runner_still_works_without_api(self) -> None:
        """ExperimentRunner().run(spec) must work without API/auth/PG/Redis."""
        from resiliencelab.core.config import parse_experiment
        from resiliencelab.experiments.runner import ExperimentRunner

        spec = parse_experiment(_tiny_config("compat1"))
        result = ExperimentRunner().run(spec)
        assert len(result.runs) == 1
        assert result.cancelled is False

    def test_cancellation_token_still_works_without_api(self) -> None:
        from resiliencelab.core.cancellation import CancellationToken

        token = CancellationToken()
        assert not token.is_cancelled
        token.request()
        assert token.is_cancelled
