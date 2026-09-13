"""Composite resilience policy and its async executor."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from resiliencelab.resilience.circuit_breaker import CircuitBreaker
from resiliencelab.resilience.concurrency import ConcurrencyLimiter
from resiliencelab.resilience.errors import (
    CallFailure,
    CircuitOpenError,
    ConcurrencyLimitExceeded,
    DeadlineExceeded,
)
from resiliencelab.resilience.jitter import Rng
from resiliencelab.resilience.retry import Retry
from resiliencelab.resilience.timeout import Timeout

T = TypeVar("T")
Operation = Callable[[], Awaitable[T]]
EventHandler = Callable[..., None]


@dataclass
class ResiliencePolicy:
    retry: Retry | None = None
    timeout: Timeout | None = None
    circuit_breaker: CircuitBreaker | None = None
    concurrency: ConcurrencyLimiter | None = None
    name: str = "policy"

    @property
    def enabled_mechanisms(self) -> list[str]:
        mechanisms: list[str] = []
        if self.retry is not None:
            mechanisms.append("retry")
        if self.timeout is not None:
            mechanisms.append("timeout")
        if self.circuit_breaker is not None:
            mechanisms.append("circuit_breaker")
        if self.concurrency is not None:
            mechanisms.append("concurrency")
        return mechanisms


@dataclass
class PolicyExecutor(Generic[T]):
    policy: ResiliencePolicy
    rng: Rng
    on_event: EventHandler | None = None
    calls: int = 0
    retries: int = 0
    rejected_circuit: int = 0
    rejected_concurrency: int = 0
    timeouts: int = 0
    backoff_seconds: float = 0.0

    def _emit(self, event: str, **fields: object) -> None:
        if self.on_event is not None:
            self.on_event(event, **fields)

    @property
    def circuit_breaker(self) -> CircuitBreaker | None:
        return self.policy.circuit_breaker

    @property
    def concurrency(self) -> ConcurrencyLimiter | None:
        return self.policy.concurrency

    @property
    def retry(self) -> Retry | None:
        return self.policy.retry

    async def execute(self, operation: Operation[T]) -> T:
        timeout = self.policy.timeout
        start = time.perf_counter()
        deadline = start + timeout.total if timeout and timeout.total else None

        concurrency = self.concurrency
        if concurrency is not None:
            try:
                await concurrency.acquire()
            except ConcurrencyLimitExceeded:
                self.rejected_concurrency += 1
                self._emit("rejected", reason="concurrency")
                raise
        try:
            cb = self.circuit_breaker
            if cb is not None and not cb.allow():
                self.rejected_circuit += 1
                self._emit("rejected", reason="circuit_open")
                raise CircuitOpenError()
            attempts_done = 0
            while True:
                if deadline is not None and time.perf_counter() >= deadline:
                    self.timeouts += 1
                    self._emit("timeout", reason="deadline")
                    raise DeadlineExceeded()
                self.calls += 1
                attempt_started = time.perf_counter()
                try:
                    result = await self._call(operation, deadline)
                except DeadlineExceeded:
                    self.timeouts += 1
                    if cb is not None:
                        cb.record_failure()
                    self._emit(
                        "attempt",
                        attempt=attempts_done + 1,
                        success=False,
                        timeout=True,
                        status=None,
                        duration=time.perf_counter() - attempt_started,
                    )
                    raise
                except CallFailure as failure:
                    attempts_done += 1
                    if cb is not None:
                        cb.record_failure()
                    self._emit(
                        "attempt",
                        attempt=attempts_done,
                        success=False,
                        timeout=False,
                        status=failure.status,
                        duration=time.perf_counter() - attempt_started,
                    )
                    if self.retry is not None and self.retry.should_retry(attempts_done, failure):
                        delay = self.retry.delay_before(attempts_done - 1, self.rng)
                        if deadline is not None:
                            remaining = deadline - time.perf_counter()
                            if remaining <= 0:
                                self.timeouts += 1
                                self._emit("timeout", reason="deadline")
                                raise DeadlineExceeded() from None
                            delay = min(delay, remaining)
                        self.backoff_seconds += delay
                        self.retries += 1
                        self._emit(
                            "retry", attempt=attempts_done + 1, delay=delay, status=failure.status
                        )
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue
                    raise
                else:
                    if cb is not None:
                        cb.record_success()
                    self._emit(
                        "attempt",
                        attempt=attempts_done + 1,
                        success=True,
                        timeout=False,
                        status=None,
                        duration=time.perf_counter() - attempt_started,
                    )
                    return result
        finally:
            if concurrency is not None:
                await concurrency.release()

    async def _call(self, operation: Operation[T], deadline: float | None) -> T:
        timeout = self.policy.timeout
        read: float | None = timeout.read if timeout else None
        if deadline is not None:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise DeadlineExceeded()
            read = remaining if read is None else min(read, remaining)
        if read is None:
            return await operation()
        try:
            async with asyncio.timeout(read):
                return await operation()
        except TimeoutError as exc:
            self._emit("timeout", reason="read_timeout")
            raise CallFailure("dependent call timed out", retryable=True, cause=exc) from exc
