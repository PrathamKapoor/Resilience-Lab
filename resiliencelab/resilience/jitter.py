"""Jitter applied to backoff delays."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class JitterKind(str, Enum):
    NONE = "none"
    FULL = "full"
    EQUAL = "equal"
    RANGE = "range"


class Rng(Protocol):
    def uniform(self, low: float, high: float) -> float: ...


@dataclass(frozen=True)
class Jitter:
    kind: JitterKind = JitterKind.NONE
    factor: float = 0.1

    def __post_init__(self) -> None:
        if self.factor < 0 or self.factor > 1:
            raise ValueError("jitter factor must be within [0, 1]")

    def apply(self, delay: float, rng: Rng) -> float:
        if delay <= 0 or self.kind is JitterKind.NONE:
            return delay
        if self.kind is JitterKind.FULL:
            return rng.uniform(0.0, delay)
        if self.kind is JitterKind.EQUAL:
            return rng.uniform(delay / 2.0, delay)
        low = delay * (1.0 - self.factor)
        high = delay * (1.0 + self.factor)
        return max(0.0, rng.uniform(low, high))
