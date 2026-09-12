from __future__ import annotations

import asyncio
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from resiliencelab.core.seeds import generator
from resiliencelab.resilience import (
    Backoff,
    BackoffKind,
    CallFailure,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    ConcurrencyLimitConfig,
    ConcurrencyLimiter,
    ConcurrencyLimitExceeded,
    Jitter,
    JitterKind,
    PolicyExecutor,
    ResiliencePolicy,
    Retry,
    RetryConfig,
    Timeout,
)


def test_backoff_fixed() -> None:
    b = Backoff(kind=BackoffKind.FIXED, base=0.25)
    assert b.delay(0) == 0.25
    assert b.delay(10) == 0.25


def test_backoff_exponential_grows_and_caps() -> None:
    b = Backoff(kind=BackoffKind.EXPONENTIAL, base=0.1, factor=2.0, max_delay=5.0)
    assert b.delay(0) == pytest.approx(0.1)
    assert b.delay(1) == pytest.approx(0.2)
    assert b.delay(10) == pytest.approx(5.0)


def test_backoff_linear() -> None:
    b = Backoff(kind=BackoffKind.LINEAR, base=0.1)
    assert b.delay(0) == pytest.approx(0.1)
    assert b.delay(2) == pytest.approx(0.3)


def test_backoff_validation() -> None:
    with pytest.raises(ValueError):
        Backoff(base=-1.0)
    with pytest.raises(ValueError):
        Backoff(factor=0.5)
    with pytest.raises(ValueError):
        Backoff(base=1.0, max_delay=0.5)


def test_backoff_zero_base_allowed() -> None:
    b = Backoff(kind=BackoffKind.FIXED, base=0.0)
    assert b.delay(0) == 0.0


def test_jitter_full_in_range() -> None:
    j = Jitter(kind=JitterKind.FULL)
    rng = generator(0)
    for _ in range(100):
        v = j.apply(1.0, rng)
        assert 0 <= v <= 1.0


def test_jitter_equal_in_range() -> None:
    j = Jitter(kind=JitterKind.EQUAL)
    rng = generator(0)
    for _ in range(100):
        v = j.apply(2.0, rng)
        assert 1.0 <= v <= 2.0


def test_jitter_none_identity() -> None:
    j = Jitter(kind=JitterKind.NONE)
    assert j.apply(1.5, generator(0)) == 1.5


def test_jitter_deterministic() -> None:
    j = Jitter(kind=JitterKind.FULL)
    a = [j.apply(1.0, generator(42)) for _ in range(20)]
    b = [j.apply(1.0, generator(42)) for _ in range(20)]
    assert a == b


class TestCircuitBreaker:
    def test_closed_to_open_on_failures(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3, recovery_window=30))
        assert cb.state is CircuitState.CLOSED
        for _ in range(2):
            assert cb.allow()
            cb.record_failure()
        assert cb.state is CircuitState.CLOSED
        assert cb.allow()
        cb.record_failure()
        assert cb.state is CircuitState.OPEN

    def test_open_blocks_requests(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_window=30))
        assert cb.allow()
        cb.record_failure()
        assert cb.state is CircuitState.OPEN
        assert cb.allow() is False

    def test_half_open_transition_after_window(self, monkeypatch) -> None:
        clock = {"t": 0.0}
        monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_window=1.0))
        assert cb.allow()
        cb.record_failure()
        assert cb.state is CircuitState.OPEN
        clock["t"] = 1.5
        assert cb.allow() is True
        assert cb.state is CircuitState.HALF_OPEN

    def test_half_open_close_on_success(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_window=0.0, half_open_probes=1)
        )
        assert cb.allow()
        cb.record_failure()
        assert cb.state is CircuitState.OPEN
        assert cb.allow() is True
        assert cb.state is CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state is CircuitState.CLOSED

    def test_half_open_reopen_on_failure(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_window=0.0, half_open_probes=1)
        )
        cb.allow()
        cb.record_failure()
        assert cb.state is CircuitState.OPEN
        cb.allow()
        assert cb.state is CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state is CircuitState.OPEN

    def test_transition_listener(self) -> None:
        transitions: list[tuple[CircuitState, CircuitState]] = []
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_window=0.0))
        cb.on_transition(lambda old, new: transitions.append((old, new)))
        cb.allow()
        cb.record_failure()
        assert (CircuitState.CLOSED, CircuitState.OPEN) in transitions

    def test_rolling_window_threshold(self) -> None:
        cfg = CircuitBreakerConfig(failure_threshold=3, rolling_window=1.0, minimum_throughput=3)
        cb = CircuitBreaker(cfg)
        for _ in range(3):
            cb.allow()
            cb.record_failure()
        assert cb.state is CircuitState.OPEN


class TestConcurrency:
    async def test_limits_inflight(self) -> None:
        lim = ConcurrencyLimiter(ConcurrencyLimitConfig(limit=2, queue_limit=None))
        await lim.acquire()
        await lim.acquire()
        assert lim.in_flight == 2
        await lim.release()
        assert lim.in_flight == 1
        await lim.release()
        assert lim.in_flight == 0

    async def test_rejects_when_queue_full(self) -> None:
        lim = ConcurrencyLimiter(ConcurrencyLimitConfig(limit=1, queue_limit=0))
        await lim.acquire()
        with pytest.raises(ConcurrencyLimitExceeded):
            await lim.acquire()
        assert lim.rejected_count == 1
        await lim.release()

    async def test_queueing(self) -> None:
        lim = ConcurrencyLimiter(ConcurrencyLimitConfig(limit=1, queue_limit=None))
        await lim.acquire()

        acquired = asyncio.Event()

        async def waiter() -> None:
            await lim.acquire()
            acquired.set()
            await lim.release()

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        assert lim.queue_depth == 1
        await lim.release()
        await asyncio.wait_for(acquired.wait(), 1.0)
        await task


class TestRetry:
    def test_should_retry_by_status(self) -> None:
        r = Retry(RetryConfig(max_attempts=3))
        assert r.should_retry(1, CallFailure("boom", status=503))
        assert not r.should_retry(1, CallFailure("boom", status=400))
        assert not r.should_retry(3, CallFailure("boom", status=503))

    def test_should_retry_by_exception(self) -> None:
        r = Retry(RetryConfig(max_attempts=3))
        assert r.should_retry(1, CallFailure("x", cause=ConnectionError()))
        assert not r.should_retry(1, CallFailure("x", cause=ValueError()))

    def test_should_retry_not_retryable(self) -> None:
        r = Retry(RetryConfig(max_attempts=3))
        assert not r.should_retry(1, CallFailure("x", retryable=False))


async def _flaky(remaining: list[int], status: int = 503) -> int:
    if remaining[0] > 0:
        remaining[0] -= 1
        raise CallFailure("downstream unavailable", status=status)
    return 42


class TestPolicyExecutor:
    async def test_retries_then_succeeds(self) -> None:
        policy = ResiliencePolicy(
            retry=Retry(
                RetryConfig(max_attempts=4, backoff=Backoff(kind=BackoffKind.FIXED, base=0.0))
            )
        )
        executor = PolicyExecutor(policy, generator(0))
        remaining = [2]
        result = await executor.execute(lambda: _flaky(remaining))
        assert result == 42
        assert executor.retries == 2
        assert executor.calls == 3

    async def test_exhausts_retries_and_raises(self) -> None:
        policy = ResiliencePolicy(
            retry=Retry(
                RetryConfig(max_attempts=3, backoff=Backoff(kind=BackoffKind.FIXED, base=0.0))
            )
        )
        executor = PolicyExecutor(policy, generator(0))
        remaining = [100]
        with pytest.raises(CallFailure):
            await executor.execute(lambda: _flaky(remaining))
        assert executor.calls == 3

    async def test_non_retryable_immediate_raise(self) -> None:
        policy = ResiliencePolicy(retry=Retry(RetryConfig(max_attempts=5)))
        executor = PolicyExecutor(policy, generator(0))

        async def op() -> int:
            raise CallFailure("bad request", status=400)

        with pytest.raises(CallFailure):
            await executor.execute(op)
        assert executor.calls == 1

    async def test_circuit_open_short_circuits(self) -> None:
        breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_window=30))
        policy = ResiliencePolicy(circuit_breaker=breaker)
        executor = PolicyExecutor(policy, generator(0))

        async def fail() -> int:
            raise CallFailure("boom", status=503)

        with pytest.raises(CallFailure):
            await executor.execute(fail)
        assert breaker.state is CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            await executor.execute(lambda: fail())
        assert executor.rejected_circuit == 1

    async def test_total_timeout_surfaces_retryable_failure(self) -> None:
        policy = ResiliencePolicy(timeout=Timeout(total=0.05))
        executor = PolicyExecutor(policy, generator(0))

        async def slow() -> int:
            await asyncio.sleep(1)
            return 1

        with pytest.raises(CallFailure) as exc_info:
            await executor.execute(slow)
        assert isinstance(exc_info.value.cause, TimeoutError)


@given(
    attempts=st.integers(min_value=1, max_value=8),
    base=st.floats(min_value=0.001, max_value=1.0),
)
@settings(max_examples=200)
def test_backoff_positive_and_monotonic(attempts: int, base: float) -> None:
    b = Backoff(kind=BackoffKind.EXPONENTIAL, base=base, factor=2.0)
    delays = [b.delay(i) for i in range(attempts)]
    assert all(d > 0 for d in delays)
    assert all(delays[i] <= delays[i + 1] for i in range(len(delays) - 1))
