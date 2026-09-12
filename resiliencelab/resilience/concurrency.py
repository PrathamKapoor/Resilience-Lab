"""Concurrency limiting with queueing and rejection semantics.

`queue_limit` controls waiting behaviour when at capacity:

* ``None`` — wait indefinitely (unbounded queueing),
* ``0`` — no queueing, reject immediately,
* ``N > 0`` — allow up to ``N`` waiting callers, reject beyond that.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from resiliencelab.resilience.errors import ConcurrencyLimitExceeded


@dataclass(frozen=True)
class ConcurrencyLimitConfig:
    limit: int = 100
    queue_limit: int | None = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("concurrency limit must be >= 1")
        if self.queue_limit is not None and self.queue_limit < 0:
            raise ValueError("queue_limit must be >= 0 or None")


@dataclass
class ConcurrencyLimiter:
    config: ConcurrencyLimitConfig = field(default_factory=ConcurrencyLimitConfig)
    _active: int = 0
    _waiting: int = 0
    _cond: asyncio.Condition = field(default_factory=asyncio.Condition, repr=False)
    rejected_count: int = 0

    @property
    def in_flight(self) -> int:
        return self._active

    @property
    def queue_depth(self) -> int:
        return self._waiting

    async def acquire(self) -> None:
        async with self._cond:
            while True:
                if self._active < self.config.limit:
                    self._active += 1
                    return
                qlimit = self.config.queue_limit
                if qlimit is not None and self._waiting >= qlimit:
                    self.rejected_count += 1
                    raise ConcurrencyLimitExceeded()
                self._waiting += 1
                try:
                    await self._cond.wait()
                finally:
                    self._waiting -= 1

    async def release(self) -> None:
        async with self._cond:
            if self._active > 0:
                self._active -= 1
            self._cond.notify(1)
