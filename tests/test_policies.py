"""Phase 3: per-service resilience policy isolation tests."""

from __future__ import annotations

import asyncio

import pytest

from resiliencelab.core.builders import build_policy
from resiliencelab.core.config import parse_experiment
from resiliencelab.core.policies import PolicyResolver
from resiliencelab.core.schema import (
    BackoffSpec,
    CircuitBreakerSpec,
    ConcurrencySpec,
    PolicySpec,
    RetrySpec,
    TimeoutSpec,
)
from resiliencelab.core.seeds import generator
from resiliencelab.experiments.runner import ExperimentRunner
from resiliencelab.metrics.collector import MetricsCollector
from resiliencelab.resilience.backoff import BackoffKind
from resiliencelab.resilience.circuit_breaker import CircuitState
from resiliencelab.resilience.errors import CallFailure, ConcurrencyLimitExceeded
from resiliencelab.resilience.policy import PolicyExecutor, ResiliencePolicy


def _default() -> PolicySpec:
    return PolicySpec(
        retry=RetrySpec(max_attempts=3),
        timeout=TimeoutSpec(total=1.0),
    )


def test_default_policy_inherited_by_all_services() -> None:
    resolver = PolicyResolver(_default())
    resolved = resolver.resolved(["payment_service", "inventory_service"])
    for name in ("payment_service", "inventory_service"):
        policy = resolved[name]
        assert policy.retry is not None and policy.retry.max_attempts == 3
        assert policy.timeout is not None and policy.timeout.total == pytest.approx(1.0)


def test_single_override_leaves_other_default() -> None:
    resolver = PolicyResolver(_default(), {"payment_service": {"retry": {"max_attempts": 5}}})
    assert resolver.resolve("payment_service").retry is not None
    assert resolver.resolve("payment_service").retry.max_attempts == 5
    assert resolver.resolve("inventory_service").retry is not None
    assert resolver.resolve("inventory_service").retry.max_attempts == 3


def test_partial_override_inherits_unspecified_fields() -> None:
    resolver = PolicyResolver(_default(), {"payment_service": {"retry": {"max_attempts": 7}}})
    policy = resolver.resolve("payment_service")
    assert policy.retry is not None and policy.retry.max_attempts == 7
    assert policy.timeout is not None and policy.timeout.total == pytest.approx(1.0)


def test_override_can_disable_retry() -> None:
    resolver = PolicyResolver(_default(), {"payment_service": {"retry": None}})
    policy = resolver.resolve("payment_service")
    assert policy.retry is None
    assert policy.timeout is not None


def test_executors_are_independent_objects() -> None:
    resolver = PolicyResolver(_default())
    a = build_policy(resolver.resolve("a"))
    b = build_policy(resolver.resolve("b"))
    assert a is not b
    assert a.retry is not b.retry


def test_circuit_breaker_state_is_isolated() -> None:
    resolver = PolicyResolver(PolicySpec(circuit_breaker=CircuitBreakerSpec(threshold=2)))
    a = build_policy(resolver.resolve("a"))
    b = build_policy(resolver.resolve("b"))
    assert a.circuit_breaker is not None and b.circuit_breaker is not None
    assert a.circuit_breaker is not b.circuit_breaker
    a.circuit_breaker.record_failure()
    a.circuit_breaker.record_failure()
    assert a.circuit_breaker.state is CircuitState.OPEN
    assert b.circuit_breaker.state is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_concurrency_isolation() -> None:
    resolver = PolicyResolver(
        PolicySpec(concurrency=ConcurrencySpec(limit=2, queue_limit=0)),
        {"b": {"concurrency": {"limit": 20, "queue_limit": 0}}},
    )
    a = build_policy(resolver.resolve("a"))
    b = build_policy(resolver.resolve("b"))
    assert a.concurrency is not None and b.concurrency is not None
    await a.concurrency.acquire()
    await a.concurrency.acquire()
    with pytest.raises(ConcurrencyLimitExceeded):
        await a.concurrency.acquire()
    for _ in range(20):
        await b.concurrency.acquire()


@pytest.mark.asyncio
async def test_retry_attempt_counts_differ() -> None:
    resolver = PolicyResolver(
        PolicySpec(
            retry=RetrySpec(max_attempts=1),
            backoff=BackoffSpec(type=BackoffKind.FIXED, base=0.0, maximum=0.0),
        ),
        {"a": {"retry": {"max_attempts": 5}}, "b": {"retry": None}},
    )
    attempts_a = await _count_attempts(build_policy(resolver.resolve("a")))
    attempts_b = await _count_attempts(build_policy(resolver.resolve("b")))
    assert attempts_a == 5
    assert attempts_b == 1


@pytest.mark.asyncio
async def test_timeout_isolation() -> None:
    resolver = PolicyResolver(
        PolicySpec(timeout=TimeoutSpec(total=0.01)),
        {"b": {"timeout": None}},
    )
    policy_a = build_policy(resolver.resolve("a"))
    policy_b = build_policy(resolver.resolve("b"))
    with pytest.raises(CallFailure):
        await PolicyExecutor(policy_a, generator(1)).execute(_slow)
    assert await PolicyExecutor(policy_b, generator(1)).execute(_slow) == "ok"


async def _slow() -> str:
    await asyncio.sleep(0.05)
    return "ok"


async def _count_attempts(policy: ResiliencePolicy) -> int:
    seen = {"attempts": 0}
    executor = PolicyExecutor(
        policy,
        generator(1),
        on_event=lambda event, **fields: (
            seen.__setitem__("attempts", seen["attempts"] + 1) if event == "attempt" else None
        ),
    )

    async def fail() -> None:
        raise CallFailure("boom", status=503)

    with pytest.raises(CallFailure):
        await executor.execute(fail)
    return seen["attempts"]


def _isolation_config(
    a_overrides: dict,
    b_overrides: dict,
    *,
    payment_failure: bool = False,
    inventory_failure: bool = False,
    services: list[dict] | None = None,
    clients: int = 4,
) -> dict:
    failures = []
    if payment_failure:
        failures.append(
            {
                "target": "payment_service",
                "type": "http_503",
                "mode": "constant",
                "probability": 1.0,
            }
        )
    if inventory_failure:
        failures.append(
            {
                "target": "inventory_service",
                "type": "http_503",
                "mode": "constant",
                "probability": 1.0,
            }
        )
    return {
        "experiment": {
            "id": "pol_iso",
            "name": "policy isolation",
            "version": 1,
            "system": {
                "services": services or [{"name": "payment_service"}, {"name": "inventory_service"}]
            },
            "workload": {
                "type": "closed_loop",
                "clients": clients,
                "duration": "0.3s",
                "warmup": "0s",
            },
            "failure": failures,
            "policy": {
                "retry": {"enabled": True, "max_attempts": 1},
                "backoff": {"type": "fixed", "base": "0.001s", "maximum": "0.001s"},
            },
            "policies": {
                "payment_service": a_overrides,
                "inventory_service": b_overrides,
            },
            "repetitions": {"count": 1, "seed_strategy": "deterministic", "base_seed": 42},
        }
    }


def _max_attempt(records, dependency: str) -> int:
    return max(
        (
            int(r["attempt"])
            for r in records
            if r.get("kind") == MetricsCollector.DOWNSTREAM and r.get("dependency") == dependency
        ),
        default=0,
    )


def _run_records(config: dict) -> list:
    return ExperimentRunner().run(parse_experiment(config)).runs[0].records


def test_cross_service_retry_leakage_and_reversal() -> None:
    five = {"retry": {"enabled": True, "max_attempts": 5}}
    none = {"retry": None}

    records = _run_records(_isolation_config(five, none, inventory_failure=True))
    assert _max_attempt(records, "payment_service") == 1
    assert _max_attempt(records, "inventory_service") == 1

    records = _run_records(_isolation_config(five, none, payment_failure=True))
    assert _max_attempt(records, "payment_service") == 5

    records = _run_records(_isolation_config(none, none, payment_failure=True))
    assert _max_attempt(records, "payment_service") == 1

    records = _run_records(_isolation_config(none, five, inventory_failure=True))
    assert _max_attempt(records, "inventory_service") == 5
    assert _max_attempt(records, "payment_service") == 1


def test_breaker_isolation_in_multi_service_run() -> None:
    config = _isolation_config(
        {
            "retry": {"enabled": True, "max_attempts": 2},
            "circuit_breaker": {"enabled": True, "threshold": 1},
        },
        {"retry": None},
        payment_failure=True,
    )
    records = _run_records(config)
    payment_open = any(
        r.get("kind") == MetricsCollector.EVENT
        and r.get("dependency") == "payment_service"
        and r.get("event") == "circuit_open"
        for r in records
    )
    inventory_open = any(
        r.get("kind") == MetricsCollector.EVENT
        and r.get("dependency") == "inventory_service"
        and r.get("event") == "circuit_open"
        for r in records
    )
    assert payment_open
    assert not inventory_open


def test_capacity_and_policy_isolation() -> None:
    config = {
        "experiment": {
            "id": "cap_iso",
            "name": "capacity+policy isolation",
            "version": 1,
            "system": {
                "services": [
                    {
                        "name": "payment_service",
                        "processing": {"distribution": "constant", "mean": "5ms"},
                        "capacity": {"max_concurrency": 2, "queue_limit": 0},
                    },
                    {
                        "name": "inventory_service",
                        "processing": {"distribution": "constant", "mean": "5ms"},
                        "capacity": {"max_concurrency": 50, "queue_limit": 0},
                    },
                ]
            },
            "workload": {"type": "closed_loop", "clients": 10, "duration": "0.3s", "warmup": "0s"},
            "failure": [],
            "policy": {
                "retry": {"enabled": True, "max_attempts": 1},
                "backoff": {"type": "fixed", "base": "0.001s", "maximum": "0.001s"},
            },
            "policies": {
                "payment_service": {"retry": {"enabled": True, "max_attempts": 3}},
                "inventory_service": {"retry": None},
            },
            "repetitions": {"count": 1, "seed_strategy": "deterministic", "base_seed": 7},
        }
    }
    records = _run_records(config)
    payment_rejected = [
        r
        for r in records
        if r.get("kind") == MetricsCollector.DOWNSTREAM
        and r.get("dependency") == "payment_service"
        and r.get("service_rejected")
    ]
    inventory_rejected = [
        r
        for r in records
        if r.get("kind") == MetricsCollector.DOWNSTREAM
        and r.get("dependency") == "inventory_service"
        and r.get("service_rejected")
    ]
    assert payment_rejected
    assert not inventory_rejected
    assert _max_attempt(records, "payment_service") == 3
    assert _max_attempt(records, "inventory_service") == 1


def test_policy_attribution_recorded() -> None:
    records = _run_records(
        _isolation_config(
            {"retry": {"enabled": True, "max_attempts": 2}},
            {"retry": None},
        )
    )
    payment_policies = {
        r.get("policy")
        for r in records
        if r.get("kind") == MetricsCollector.DOWNSTREAM and r.get("dependency") == "payment_service"
    }
    inventory_policies = {
        r.get("policy")
        for r in records
        if r.get("kind") == MetricsCollector.DOWNSTREAM
        and r.get("dependency") == "inventory_service"
    }
    assert len(payment_policies) == 1 and "retry" in next(iter(payment_policies))
    assert len(inventory_policies) == 1 and "retry" not in next(iter(inventory_policies))
    assert payment_policies != inventory_policies
