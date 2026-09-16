"""Tests for endpoint_mix runtime semantics.

Endpoint mix is a workload configuration that specifies multiple endpoints
with equal probability. The selection must be deterministic given the same
seed and request_id.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from resiliencelab.core.schema import WorkloadSpec, WorkloadType
from resiliencelab.metrics.collector import MetricsCollector
from resiliencelab.workloads.generator import WorkloadGenerator


def _make_generator(
    endpoints: list[str],
    seed: int = 42,
    clients: int = 1,
    duration: float = 0.1,
) -> WorkloadGenerator:
    spec = WorkloadSpec(
        type=WorkloadType.CLOSED_LOOP,
        clients=clients,
        duration=duration,
        endpoint_mix=endpoints,
    )
    send = AsyncMock()
    send.return_value = type("R", (), {"status_code": 200})()
    metrics = MetricsCollector("test_exp", "test_run", seed)
    return WorkloadGenerator(spec, send, metrics, seed)


class TestEndpointMixSelection:
    def test_single_endpoint_always_selected(self) -> None:
        gen = _make_generator(["/api/v1/health"])
        for req_id in range(100):
            assert gen._select_endpoint(req_id) == "/api/v1/health"

    def test_deterministic_selection(self) -> None:
        gen1 = _make_generator(["/a", "/b", "/c"], seed=42)
        gen2 = _make_generator(["/a", "/b", "/c"], seed=42)
        for req_id in range(200):
            assert gen1._select_endpoint(req_id) == gen2._select_endpoint(req_id)

    def test_different_seeds_different_selection(self) -> None:
        gen1 = _make_generator(["/a", "/b"], seed=42)
        gen2 = _make_generator(["/a", "/b"], seed=99)
        # At least some requests should differ (statistical, not guaranteed)
        results1 = [gen1._select_endpoint(i) for i in range(100)]
        results2 = [gen2._select_endpoint(i) for i in range(100)]
        assert results1 != results2

    def test_uniform_distribution(self) -> None:
        gen = _make_generator(["/a", "/b", "/c"], seed=42)
        counts = {"a": 0, "b": 0, "c": 0}
        n = 3000
        for req_id in range(n):
            ep = gen._select_endpoint(req_id)
            counts[ep[1:]] += 1
        # Each should be roughly 33%
        for key, count in counts.items():
            ratio = count / n
            assert 0.25 < ratio < 0.42, f"endpoint {key} got {ratio:.3f}, expected ~0.333"

    def test_two_endpoints_distribution(self) -> None:
        gen = _make_generator(["/fast", "/slow"], seed=42)
        counts = {"/fast": 0, "/slow": 0}
        n = 2000
        for req_id in range(n):
            ep = gen._select_endpoint(req_id)
            counts[ep] += 1
        for key, count in counts.items():
            ratio = count / n
            assert 0.4 < ratio < 0.6, f"endpoint {key} got {ratio:.3f}, expected ~0.5"

    def test_single_endpoint_backward_compat(self) -> None:
        gen = _make_generator(["/"])
        for req_id in range(50):
            assert gen._select_endpoint(req_id) == "/"


class TestEndpointMixMetrics:
    def test_operation_recorded_in_metrics(self) -> None:
        gen = _make_generator(["/a", "/b"], seed=42, duration=0.5)
        asyncio.run(gen.run())
        records = gen.metrics.records()
        request_records = [r for r in records if r.get("kind") == "request"]
        assert len(request_records) > 0
        for r in request_records:
            assert "operation" in r
            assert r["operation"] in ("/a", "/b")

    def test_single_endpoint_operation_always_same(self) -> None:
        gen = _make_generator(["/health"], seed=42, duration=0.5)
        asyncio.run(gen.run())
        records = gen.metrics.records()
        request_records = [r for r in records if r.get("kind") == "request"]
        for r in request_records:
            assert r["operation"] == "/health"

    def test_events_contain_operation(self) -> None:
        gen = _make_generator(["/x", "/y"], seed=42, duration=0.5)
        asyncio.run(gen.run())
        events = gen.metrics.events()
        completed = [e for e in events if e.event_type == "RequestCompleted"]
        assert len(completed) > 0
        for e in completed:
            assert e.operation in ("/x", "/y")


class TestEndpointMixSchema:
    def test_empty_endpoint_mix_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorkloadSpec(endpoint_mix=[])

    def test_default_single_slash(self) -> None:
        spec = WorkloadSpec()
        assert spec.endpoint_mix == ["/"]

    def test_multiple_endpoints(self) -> None:
        spec = WorkloadSpec(endpoint_mix=["/a", "/b", "/c"])
        assert spec.endpoint_mix == ["/a", "/b", "/c"]

    def test_endpoint_mix_preserved_in_spec(self) -> None:
        spec = WorkloadSpec(endpoint_mix=["/users", "/orders", "/products"])
        assert len(spec.endpoint_mix) == 3


class TestEndpointMixSummarize:
    def test_summarize_by_endpoint(self) -> None:
        from resiliencelab.metrics.transforms import summarize_by_endpoint

        records = [
            {"kind": "request", "operation": "/a", "success": True, "latency": 0.01},
            {"kind": "request", "operation": "/a", "success": True, "latency": 0.02},
            {"kind": "request", "operation": "/b", "success": False, "latency": 0.05},
            {"kind": "request", "operation": "/b", "success": True, "latency": 0.01},
        ]
        result = summarize_by_endpoint(records)
        assert "/a" in result
        assert "/b" in result
        assert result["/a"]["total"] == 2.0
        assert result["/a"]["availability"] == 1.0
        assert result["/b"]["total"] == 2.0
        assert result["/b"]["availability"] == 0.5

    def test_summarize_by_endpoint_empty(self) -> None:
        from resiliencelab.metrics.transforms import summarize_by_endpoint

        result = summarize_by_endpoint([])
        assert result == {}

    def test_summarize_by_endpoint_default_slash(self) -> None:
        from resiliencelab.metrics.transforms import summarize_by_endpoint

        records = [
            {"kind": "request", "success": True, "latency": 0.01},
        ]
        result = summarize_by_endpoint(records)
        assert "/" in result
