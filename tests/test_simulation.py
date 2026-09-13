"""Tests for Phase 2 controlled simulation: processing, network, capacity."""

from __future__ import annotations

import asyncio

import pytest

from resiliencelab.core.config import parse_experiment
from resiliencelab.core.schema import (
    CapacitySpec,
    NetworkEdgeSpec,
    NetworkLinkSpec,
    NetworkSpec,
    ProcessingSpec,
)
from resiliencelab.core.seeds import generator
from resiliencelab.experiments.runner import ExperimentRunner
from resiliencelab.faults.model import LatencyDistribution
from resiliencelab.metrics.transforms import latency_components
from resiliencelab.resilience.errors import CallFailure
from resiliencelab.services.capacity import ServiceCapacity, ServiceSaturated
from resiliencelab.services.dependency import DependencyService
from resiliencelab.services.network import network_delay, resolve_network_link
from resiliencelab.services.processing import sample_processing_latency


def test_processing_constant() -> None:
    spec = ProcessingSpec(distribution=LatencyDistribution.CONSTANT, mean=0.02)
    assert sample_processing_latency(spec, generator(1)) == pytest.approx(0.02)


def test_processing_none_is_zero() -> None:
    assert sample_processing_latency(None, generator(1)) == 0.0


def test_processing_normal_reproducible_and_non_negative() -> None:
    spec = ProcessingSpec(distribution=LatencyDistribution.NORMAL, mean=0.02, std=0.005)
    a = [sample_processing_latency(spec, generator(7)) for _ in range(50)]
    b = [sample_processing_latency(spec, generator(7)) for _ in range(50)]
    assert a == b
    assert all(v >= 0 for v in a)


def test_processing_uniform_bounded() -> None:
    spec = ProcessingSpec(distribution=LatencyDistribution.UNIFORM, min=0.01, max=0.03)
    values = [sample_processing_latency(spec, generator(2)) for _ in range(100)]
    assert all(0.01 <= v <= 0.03 for v in values)


def test_resolve_network_edge_precedence() -> None:
    net = NetworkSpec(
        default=NetworkLinkSpec(latency=0.01, jitter=0.0),
        edges=[NetworkEdgeSpec(source="a", target="b", latency=0.04, jitter=0.01)],
    )
    assert resolve_network_link(net, "a", "c") == NetworkLinkSpec(latency=0.01, jitter=0.0)
    assert resolve_network_link(net, "a", "b") == NetworkLinkSpec(latency=0.04, jitter=0.01)


def test_resolve_network_none() -> None:
    assert resolve_network_link(None, "a", "b") is None


def test_network_delay_jitter_bounds_and_reproducible() -> None:
    link = NetworkLinkSpec(latency=0.02, jitter=0.005)
    delays = [network_delay(link, generator(3)) for _ in range(200)]
    assert all(0.015 - 1e-9 <= d <= 0.025 + 1e-9 for d in delays)
    rng_a = generator(9)
    rng_b = generator(9)
    assert [network_delay(link, rng_a) for _ in range(5)] == [
        network_delay(link, rng_b) for _ in range(5)
    ]


def test_network_delay_no_jitter_is_base() -> None:
    assert network_delay(NetworkLinkSpec(latency=0.03, jitter=0.0), generator(1)) == pytest.approx(
        0.03
    )


@pytest.mark.asyncio
async def test_capacity_reject_when_full() -> None:
    cap = ServiceCapacity(max_concurrency=1, queue_limit=0)
    await cap.acquire()
    with pytest.raises(ServiceSaturated):
        await cap.acquire()
    assert cap.rejected_count == 1
    await cap.release()


@pytest.mark.asyncio
async def test_capacity_queue_wait_and_peak() -> None:
    cap = ServiceCapacity(max_concurrency=1, queue_limit=None)
    await cap.acquire()
    result: list[float] = []

    async def wait_then_release() -> None:
        wait = await cap.acquire()
        result.append(wait)
        await cap.release()

    task = asyncio.create_task(wait_then_release())
    await asyncio.sleep(0.02)
    await cap.release()
    await task
    assert result[0] >= 0.0
    assert cap.peak_queue_depth >= 1


def test_capacity_snapshot_fields() -> None:
    cap = ServiceCapacity(max_concurrency=2, queue_limit=1)
    snap = cap.snapshot()
    assert set(snap) == {
        "capacity",
        "in_flight",
        "queue_depth",
        "peak_queue_depth",
        "utilization",
        "rejected_count",
    }
    assert snap["capacity"] == 2.0
    assert snap["utilization"] == 0.0


@pytest.mark.asyncio
async def test_dependency_processing_recorded() -> None:
    context: dict = {}
    svc = DependencyService(
        "svc",
        processing=ProcessingSpec(distribution=LatencyDistribution.CONSTANT, mean=0.001),
    )
    await svc.invoke(1, 2, attempt_context=context)
    assert context["processing_latency"] == pytest.approx(0.001)
    assert context.get("service_rejected", False) is False


@pytest.mark.asyncio
async def test_dependency_capacity_rejection_recorded_and_raises() -> None:
    svc = DependencyService("svc", capacity=CapacitySpec(max_concurrency=1, queue_limit=0))
    assert svc._capacity is not None
    await svc._capacity.acquire()
    context: dict = {}
    with pytest.raises(CallFailure):
        await svc.invoke(1, 2, attempt_context=context)
    assert context.get("service_rejected") is True


def test_runner_reflects_simulated_components() -> None:
    spec = parse_experiment(
        {
            "experiment": {
                "id": "sim_components",
                "name": "simulated components",
                "version": 1,
                "system": {
                    "services": [
                        {
                            "name": "payment_service",
                            "processing": {"distribution": "constant", "mean": "5ms"},
                        }
                    ],
                    "network": {"default": {"latency": "5ms", "jitter": "0ms"}},
                },
                "workload": {
                    "type": "closed_loop",
                    "clients": 4,
                    "duration": "0.3s",
                    "warmup": "0.05s",
                },
                "failure": [],
                "repetitions": {"count": 1, "seed_strategy": "deterministic", "base_seed": 1},
            }
        }
    )
    result = ExperimentRunner().run(spec)
    records = [r for run in result.runs for r in run.records]
    components = latency_components(records)
    assert components["processing"] == pytest.approx(0.005, abs=0.001)
    assert components["network"] == pytest.approx(0.005, abs=0.001)
