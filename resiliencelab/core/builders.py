"""Convert declarative schema models into runtime resilience/fault objects."""

from __future__ import annotations

from resiliencelab.core.schema import (
    BackoffSpec,
    CircuitBreakerSpec,
    ConcurrencySpec,
    FailureSpec,
    PolicySpec,
    RetrySpec,
    TimeoutSpec,
)
from resiliencelab.faults.model import FaultInjector, FaultSpec
from resiliencelab.resilience.backoff import Backoff
from resiliencelab.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from resiliencelab.resilience.concurrency import ConcurrencyLimitConfig, ConcurrencyLimiter
from resiliencelab.resilience.jitter import Jitter
from resiliencelab.resilience.policy import ResiliencePolicy
from resiliencelab.resilience.retry import Retry, RetryBudget, RetryConfig
from resiliencelab.resilience.timeout import Timeout


def build_backoff(spec: BackoffSpec) -> Backoff:
    return Backoff(
        kind=spec.type,
        base=spec.base,
        max_delay=spec.maximum,
        factor=spec.factor,
    )


def build_jitter(spec: BackoffSpec) -> Jitter:
    return Jitter(kind=spec.jitter, factor=spec.jitter_factor)


def build_retry(retry_spec: RetrySpec | None, backoff_spec: BackoffSpec) -> Retry | None:
    if retry_spec is None:
        return None
    budget = None
    if retry_spec.budget_max_retries is not None:
        budget = RetryBudget(
            max_retries=retry_spec.budget_max_retries,
            window=retry_spec.budget_window,
        )
    return Retry(
        RetryConfig(
            max_attempts=retry_spec.max_attempts,
            retryable_statuses=frozenset(retry_spec.retryable_statuses),
            backoff=build_backoff(backoff_spec),
            jitter=build_jitter(backoff_spec),
        ),
        budget=budget,
    )


def build_circuit_breaker(spec: CircuitBreakerSpec | None) -> CircuitBreaker | None:
    if spec is None:
        return None
    return CircuitBreaker(
        CircuitBreakerConfig(
            failure_threshold=spec.threshold,
            recovery_window=spec.recovery_window,
            half_open_probes=spec.half_open_probes,
            rolling_window=spec.rolling_window,
            minimum_throughput=spec.minimum_throughput,
        )
    )


def build_timeout(spec: TimeoutSpec | None) -> Timeout | None:
    if spec is None:
        return None
    if spec.connect is None and spec.read is None and spec.total is None:
        return None
    return Timeout(connect=spec.connect, read=spec.read, total=spec.total)


def build_concurrency(spec: ConcurrencySpec | None) -> ConcurrencyLimiter | None:
    if spec is None:
        return None
    return ConcurrencyLimiter(
        ConcurrencyLimitConfig(limit=spec.limit, queue_limit=spec.queue_limit)
    )


def build_policy(spec: PolicySpec) -> ResiliencePolicy:
    retry = build_retry(spec.retry, spec.backoff)
    name = (
        "+".join(
            [
                m
                for m in (
                    "retry" if retry else None,
                    "backoff" if (retry and spec.backoff.type.value != "fixed") else None,
                    "circuit_breaker" if spec.circuit_breaker else None,
                    "timeout" if build_timeout(spec.timeout) else None,
                    "concurrency" if spec.concurrency else None,
                )
                if m
            ]
        )
        or "baseline"
    )
    return ResiliencePolicy(
        retry=retry,
        timeout=build_timeout(spec.timeout),
        circuit_breaker=build_circuit_breaker(spec.circuit_breaker),
        concurrency=build_concurrency(spec.concurrency),
        name=name,
    )


def build_fault_spec(spec: FailureSpec) -> FaultSpec:
    return FaultSpec(
        kind=spec.type,
        mode=spec.mode,
        probability=spec.probability,
        start=spec.start,
        duration=spec.duration,
        period=spec.period,
        latency_distribution=spec.latency_distribution,
        latency_mean=spec.latency_mean,
        latency_std=spec.latency_std,
        latency_min=spec.latency_min,
        latency_max=spec.latency_max,
        status_code=spec.status_code,
    )


def build_fault_injectors(specs: list[FailureSpec]) -> list[FaultInjector]:
    return [FaultInjector(build_fault_spec(spec)) for spec in specs]
