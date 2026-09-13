"""Tests for workload arrival semantics and latency measurement attribution."""

from __future__ import annotations

import pytest

from resiliencelab.core.schema import ArrivalDistribution, WorkloadSpec, WorkloadType
from resiliencelab.core.seeds import generator
from resiliencelab.metrics.collector import MetricsCollector
from resiliencelab.metrics.transforms import latency_components
from resiliencelab.workloads.arrivals import ArrivalModel


def _spec(**overrides) -> WorkloadSpec:
    defaults = {
        "type": WorkloadType.CONSTANT_RATE,
        "arrival_rate": 100.0,
        "duration": 10.0,
        "burst_size": 3,
        "burst_interval": 5.0,
        "period": 10.0,
        "burstiness": 1.0,
    }
    defaults.update(overrides)
    return WorkloadSpec(**defaults)


def test_closed_loop_has_no_arrival_model() -> None:
    with pytest.raises(ValueError):
        ArrivalModel(_spec(type=WorkloadType.CLOSED_LOOP)).gap(0.0, generator(1))


def test_constant_rate_is_fixed_gap() -> None:
    model = ArrivalModel(_spec(type=WorkloadType.CONSTANT_RATE, arrival_rate=100.0))
    assert model.gap(0.0, generator(1)) == pytest.approx(0.01)
    assert model.gap(17.3, generator(1)) == pytest.approx(0.01)


def test_open_loop_constant_distribution_is_fixed() -> None:
    spec = _spec(type=WorkloadType.OPEN_LOOP, distribution=ArrivalDistribution.CONSTANT)
    model = ArrivalModel(spec)
    gaps = [model.gap(0.0, generator(2)) for _ in range(20)]
    assert all(g == pytest.approx(0.01) for g in gaps)


def test_open_loop_poisson_is_stochastic_and_positive() -> None:
    spec = _spec(type=WorkloadType.OPEN_LOOP, distribution=ArrivalDistribution.POISSON)
    model = ArrivalModel(spec)
    rng = generator(3)
    gaps = [model.gap(0.0, rng) for _ in range(200)]
    assert all(g > 0 for g in gaps)
    assert len({round(g, 6) for g in gaps}) > 1


def test_random_is_uniform_bounded() -> None:
    spec = _spec(type=WorkloadType.RANDOM, arrival_rate=100.0)
    model = ArrivalModel(spec)
    rng = generator(4)
    gaps = [model.gap(0.0, rng) for _ in range(200)]
    assert all(0.0 <= g <= 0.02 for g in gaps)
    assert len({round(g, 6) for g in gaps}) > 1


def test_burst_pattern_alternates() -> None:
    model = ArrivalModel(_spec(type=WorkloadType.BURST, arrival_rate=100.0))
    gaps = [model.gap(0.0, generator(5)) for _ in range(6)]
    assert gaps[:2] == [pytest.approx(0.01)] * 2
    assert gaps[2] == pytest.approx(5.0)
    assert gaps[3:5] == [pytest.approx(0.01)] * 2
    assert gaps[5] == pytest.approx(5.0)


def test_periodic_rate_oscillates() -> None:
    spec = _spec(type=WorkloadType.PERIODIC, arrival_rate=100.0, period=10.0, burstiness=0.5)
    model = ArrivalModel(spec)
    at_peak = model.gap(2.5, generator(6))
    at_trough = model.gap(7.5, generator(6))
    assert at_peak == pytest.approx(1.0 / 150.0)
    assert at_trough == pytest.approx(1.0 / 50.0)
    assert at_peak < at_trough


def test_ramp_gap_decreases_over_time() -> None:
    model = ArrivalModel(_spec(type=WorkloadType.RAMP, arrival_rate=100.0, duration=10.0))
    early = model.gap(0.0, generator(7))
    late = model.gap(10.0, generator(7))
    assert early == pytest.approx(0.1)
    assert late == pytest.approx(0.01)
    assert early > late


def test_stochastic_gaps_are_reproducible() -> None:
    spec = _spec(type=WorkloadType.OPEN_LOOP, distribution=ArrivalDistribution.POISSON)
    model_a = ArrivalModel(spec)
    model_b = ArrivalModel(spec)
    rng_a = generator(99)
    rng_b = generator(99)
    a = [model_a.gap(0.3, rng_a) for _ in range(10)]
    b = [model_b.gap(0.3, rng_b) for _ in range(10)]
    assert a == b


def _request(rid: int, latency: float, success: bool = True) -> dict:
    return {
        "kind": MetricsCollector.REQUEST,
        "request_id": rid,
        "latency": latency,
        "success": success,
    }


def _downstream(rid: int, latency: float) -> dict:
    return {"kind": MetricsCollector.DOWNSTREAM, "request_id": rid, "latency": latency}


def _retry_event(rid: int, delay: float) -> dict:
    return {"kind": MetricsCollector.EVENT, "request_id": rid, "event": "retry", "delay": delay}


def test_latency_components_decompose_total() -> None:
    records = [
        _request(0, 0.08),
        _downstream(0, 0.03),
        _downstream(0, 0.02),
        _retry_event(0, 0.01),
    ]
    components = latency_components(records)
    assert components["total"] == pytest.approx(0.08)
    assert components["service"] == pytest.approx(0.05)
    assert components["retry"] == pytest.approx(0.01)
    assert components["other"] == pytest.approx(0.02)


def test_latency_components_empty_is_zeroed() -> None:
    assert latency_components([]) == {
        "total": 0.0,
        "service": 0.0,
        "retry": 0.0,
        "other": 0.0,
    }


def test_latency_components_average_across_requests() -> None:
    records = [
        _request(0, 0.10),
        _downstream(0, 0.08),
        _request(1, 0.04),
        _downstream(1, 0.04),
    ]
    components = latency_components(records)
    assert components["total"] == pytest.approx(0.07)
    assert components["service"] == pytest.approx(0.06)
    assert components["retry"] == pytest.approx(0.0)
    assert components["other"] == pytest.approx(0.01)
