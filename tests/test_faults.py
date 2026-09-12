from __future__ import annotations

import pytest

from resiliencelab.core.seeds import generator
from resiliencelab.faults.model import (
    FailureKind,
    FaultInjector,
    FaultSpec,
    TemporalMode,
)


def _rng(seed: int = 0):
    return generator(seed)


def test_http_fault_active() -> None:
    inj = FaultInjector(FaultSpec(kind=FailureKind.HTTP_503, probability=1.0))
    event = inj.evaluate(0.0, _rng())
    assert event is not None
    assert event.status_code == 503


def test_probability_zero_never_fails() -> None:
    inj = FaultInjector(FaultSpec(kind=FailureKind.HTTP_503, probability=0.0))
    assert inj.evaluate(0.0, _rng()) is None


def test_probability_one_always_fails() -> None:
    inj = FaultInjector(FaultSpec(kind=FailureKind.HTTP_503, probability=1.0))
    for i in range(50):
        assert inj.evaluate(float(i), _rng(i)) is not None


def test_burst_only_during_window() -> None:
    inj = FaultInjector(
        FaultSpec(
            kind=FailureKind.HTTP_503,
            mode=TemporalMode.BURST,
            probability=1.0,
            start=5.0,
            duration=10.0,
        )
    )
    assert inj.is_active(3.0) is False
    assert inj.is_active(6.0) is True
    assert inj.is_active(14.9) is True
    assert inj.is_active(15.1) is False


def test_periodic_bursts() -> None:
    inj = FaultInjector(
        FaultSpec(
            kind=FailureKind.HTTP_503,
            mode=TemporalMode.PERIODIC,
            probability=1.0,
            start=0.0,
            duration=5.0,
            period=10.0,
        )
    )
    assert inj.is_active(2.0) is True
    assert inj.is_active(8.0) is False
    assert inj.is_active(12.0) is True


def test_ramp_probability() -> None:
    inj = FaultInjector(
        FaultSpec(
            kind=FailureKind.HTTP_503,
            mode=TemporalMode.RAMP,
            probability=0.9,
            start=0.0,
            duration=10.0,
        )
    )
    assert inj.failure_probability(0.0) == 0.0
    assert inj.failure_probability(5.0) == pytest.approx(0.45)
    assert inj.failure_probability(20.0) == pytest.approx(0.9)


def test_latency_samples_within_range() -> None:
    inj = FaultInjector(
        FaultSpec(
            kind=FailureKind.LATENCY,
            probability=1.0,
            latency_min=0.1,
            latency_max=0.2,
        )
    )
    for i in range(20):
        event = inj.evaluate(0.0, _rng(i))
        assert event is not None
        assert 0.1 <= event.latency <= 0.2


def test_deterministic_fault_decisions() -> None:
    spec = FaultSpec(kind=FailureKind.HTTP_503, mode=TemporalMode.RANDOM, probability=0.5)
    a = [FaultInjector(spec).evaluate(1.0, _rng(42)) is not None for _ in range(20)]
    b = [FaultInjector(spec).evaluate(1.0, _rng(42)) is not None for _ in range(20)]
    assert a == b
