"""Retry policy composed of backoff, jitter, classification, and budget."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from resiliencelab.resilience.backoff import Backoff
from resiliencelab.resilience.errors import CallFailure, RetryBudgetExhausted
from resiliencelab.resilience.jitter import Jitter, Rng

DEFAULT_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
)


class RetryBudget:
    def __init__(self, max_retries: int, window: float) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if window <= 0:
            raise ValueError("window must be positive")
        self._max = max_retries
        self._window = window
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) < self._max:
                self._timestamps.append(now)
                return True
            return False

    @property
    def remaining(self) -> int:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            return self._max - len(self._timestamps)


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    retryable_statuses: frozenset[int] = DEFAULT_RETRYABLE_STATUSES
    retryable_exceptions: tuple[type[BaseException], ...] = DEFAULT_RETRYABLE_EXCEPTIONS
    backoff: Backoff = field(default_factory=Backoff)
    jitter: Jitter = field(default_factory=Jitter)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")


@dataclass
class Retry:
    config: RetryConfig = field(default_factory=RetryConfig)
    budget: RetryBudget | None = None

    def should_retry(self, attempts_done: int, failure: CallFailure) -> bool:
        if attempts_done >= self.config.max_attempts:
            return False
        if not failure.retryable:
            return False
        status = failure.status
        if status is not None and status not in self.config.retryable_statuses:
            return False
        cause = failure.cause
        if cause is not None and not any(
            isinstance(cause, exc) for exc in self.config.retryable_exceptions
        ):
            return False
        if self.budget is not None and not self.budget.acquire():
            raise RetryBudgetExhausted()
        return True

    def delay_before(self, retries_done: int, rng: Rng) -> float:
        return self.config.jitter.apply(self.config.backoff.delay(retries_done), rng)
