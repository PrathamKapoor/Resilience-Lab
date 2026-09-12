"""Circuit breaker state machine."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_window: float = 30.0
    half_open_probes: int = 1
    rolling_window: float | None = None
    minimum_throughput: int = 1


@dataclass
class CircuitBreaker:
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    _state: CircuitState = CircuitState.CLOSED
    _consecutive_failures: int = 0
    _opened_at: float = 0.0
    _half_open_inflight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _recent: deque[tuple[float, bool]] = field(default_factory=deque, repr=False)
    _listeners: list[Callable[[CircuitState, CircuitState], None]] = field(
        default_factory=list, repr=False
    )

    def __post_init__(self) -> None:
        if self.config.failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if self.config.recovery_window < 0:
            raise ValueError("recovery_window must be >= 0")
        if self.config.half_open_probes < 1:
            raise ValueError("half_open_probes must be >= 1")

    @property
    def state(self) -> CircuitState:
        return self._state

    def on_transition(self, listener: Callable[[CircuitState, CircuitState], None]) -> None:
        self._listeners.append(listener)

    def _transition(self, new_state: CircuitState) -> None:
        if new_state is self._state:
            return
        old = self._state
        self._state = new_state
        for listener in list(self._listeners):
            listener(old, new_state)

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if self._state is CircuitState.OPEN:
                if now - self._opened_at >= self.config.recovery_window:
                    self._transition_to_half_open()
                    self._half_open_inflight += 1
                    return True
                return False
            if self._state is CircuitState.HALF_OPEN:
                if self._half_open_inflight >= self.config.half_open_probes:
                    return False
                self._half_open_inflight += 1
                return True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._record_recent(True)
            self._consecutive_failures = 0
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_inflight = max(0, self._half_open_inflight - 1)
                if self._half_open_inflight == 0:
                    self._transition(CircuitState.CLOSED)

    def record_failure(self) -> None:
        with self._lock:
            self._record_recent(False)
            self._consecutive_failures += 1
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_inflight = max(0, self._half_open_inflight - 1)
                self._open()
                return
            if (
                self._consecutive_failures >= self.config.failure_threshold
                and self._threshold_met()
            ):
                self._open()

    def _transition_to_half_open(self) -> None:
        self._transition(CircuitState.HALF_OPEN)
        self._half_open_inflight = 0

    def _open(self) -> None:
        self._opened_at = time.monotonic()
        self._consecutive_failures = 0
        self._transition(CircuitState.OPEN)

    def _record_recent(self, success: bool) -> None:
        if self.config.rolling_window is None:
            return
        now = time.monotonic()
        cutoff = now - self.config.rolling_window
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()
        self._recent.append((now, success))

    def _threshold_met(self) -> bool:
        cfg = self.config
        if cfg.rolling_window is not None:
            if len(self._recent) < cfg.minimum_throughput:
                return False
            failures = sum(1 for _, ok in self._recent if not ok)
            return failures >= cfg.failure_threshold
        return self._consecutive_failures >= cfg.failure_threshold

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._half_open_inflight = 0
            self._recent.clear()

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures
