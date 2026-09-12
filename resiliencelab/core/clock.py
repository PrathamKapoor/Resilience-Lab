"""A monotonic experiment clock with a configurable zero point."""

from __future__ import annotations

import time


class Clock:
    def __init__(self, start_offset: float = 0.0) -> None:
        self._start = time.perf_counter() - start_offset

    def now(self) -> float:
        return time.perf_counter() - self._start

    def reset(self, start_offset: float = 0.0) -> None:
        self._start = time.perf_counter() - start_offset
