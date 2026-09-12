from __future__ import annotations

from resiliencelab.core.config import parse_experiment
from resiliencelab.core.seeds import generator, generator_for
from resiliencelab.experiments.factorial import CORE_FACTORS, generate_matrix
from resiliencelab.faults.model import FailureKind, FaultInjector, FaultSpec


def _base():
    return parse_experiment({"experiment": {"id": "exp_m", "name": "m"}})


def test_seeded_streams_are_deterministic() -> None:
    a = generator_for(11, 3).random(5).tolist()
    b = generator_for(11, 3).random(5).tolist()
    c = generator_for(11, 4).random(5).tolist()
    assert a == b
    assert a != c


def test_fault_decisions_reproducible() -> None:
    spec = FaultSpec(kind=FailureKind.HTTP_503, probability=0.5)
    rng_a, rng_b = generator(9), generator(9)
    first = [FaultInjector(spec).evaluate(0.0, rng_a) is not None for _ in range(30)]
    second = [FaultInjector(spec).evaluate(0.0, rng_b) is not None for _ in range(30)]
    assert first == second
    assert any(first) and not all(first)


def test_factorial_count_and_ids() -> None:
    variants = generate_matrix(
        _base(), {"policy.retry": [None, {"enabled": True, "max_attempts": 2}]}
    )
    assert len(variants) == 2
    assert variants[0].id != variants[1].id
    assert {v.policy.retry is None for v in variants} == {True, False}


def test_core_factors_shape() -> None:
    assert CORE_FACTORS
    for values in CORE_FACTORS.values():
        assert isinstance(values, list) and len(values) >= 2
    subset = {k: CORE_FACTORS[k] for k in ["policy.retry", "policy.circuit_breaker"]}
    variants = generate_matrix(_base(), subset)
    assert len(variants) == 4
