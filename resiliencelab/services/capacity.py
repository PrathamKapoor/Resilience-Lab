"""Simulated service-side capacity and queueing model.

This models a dependency's *server-side* processing capacity, which is a
different experimental variable from a *client-side* concurrency limit
(see ``resilience/concurrency.py``). Requests enter a queue when all
processing slots are occupied; the queue is unbounded (``queue_limit=None``),
rejecting (``queue_limit=0``), or bounded (``queue_limit>0``).

Queue waiting is wall-clock (the calling coroutine genuinely awaits a slot),
because the experiment's workloads and measurements run in real time. The
*decisions* (queue vs reject) are deterministic given arrival order.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from resiliencelab.resilience.errors import CallFailure


class ServiceSaturated(CallFailure):
    """A service rejected a request because its capacity and queue are full."""

    def __init__(self, message: str = "service capacity saturated") -> None:
        super().__init__(message, status=503, retryable=True)


@dataclass
class ServiceCapacity:
    max_concurrency: int = 50
    queue_limit: int | None = None

    _active: int = 0
    _waiting: int = 0
    _cond: asyncio.Condition = field(default_factory=asyncio.Condition, repr=False)
    rejected_count: int = 0
    peak_queue_depth: int = 0

    @property
    def capacity(self) -> int:
        return self.max_concurrency

    @property
    def in_flight(self) -> int:
        return self._active

    @property
    def queue_depth(self) -> int:
        return self._waiting

    @property
    def utilization(self) -> float:
        return self._active / self.max_concurrency if self.max_concurrency else 0.0

    async def acquire(self) -> float:
        """Acquire a processing slot; returns wall-clock queue wait in seconds.

        Raises :class:`ServiceSaturated` when the queue is full and rejection
        is configured.
        """
        async with self._cond:
            queued_at: float | None = None
            while True:
                if self._active < self.max_concurrency:
                    self._active += 1
                    if queued_at is not None:
                        return time.monotonic() - queued_at
                    return 0.0
                qlimit = self.queue_limit
                if qlimit is not None and self._waiting >= qlimit:
                    self.rejected_count += 1
                    raise ServiceSaturated()
                self._waiting += 1
                self.peak_queue_depth = max(self.peak_queue_depth, self._waiting)
                if queued_at is None:
                    queued_at = time.monotonic()
                try:
                    await self._cond.wait()
                finally:
                    self._waiting -= 1

    async def release(self) -> None:
        async with self._cond:
            if self._active > 0:
                self._active -= 1
            self._cond.notify(1)

    def snapshot(self) -> dict[str, float]:
        return {
            "capacity": float(self.capacity),
            "in_flight": float(self.in_flight),
            "queue_depth": float(self.queue_depth),
            "peak_queue_depth": float(self.peak_queue_depth),
            "utilization": self.utilization,
            "rejected_count": float(self.rejected_count),
        }
