"""Backoff delay strategies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BackoffKind(str, Enum):
    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    CAPPED_EXPONENTIAL = "capped_exponential"


@dataclass(frozen=True)
class Backoff:
    kind: BackoffKind = BackoffKind.EXPONENTIAL
    base: float = 0.1
    max_delay: float = 5.0
    factor: float = 2.0

    def __post_init__(self) -> None:
        if self.base < 0:
            raise ValueError("backoff base must be non-negative")
        if self.factor < 1:
            raise ValueError("backoff factor must be >= 1")
        if self.max_delay < self.base:
            raise ValueError("backoff max_delay must be >= base")

    def delay(self, retry: int) -> float:
        if retry < 0:
            raise ValueError("retry index must be >= 0")
        if self.kind is BackoffKind.FIXED:
            raw = float(self.base)
        elif self.kind is BackoffKind.LINEAR:
            raw = self.base * (retry + 1)
        else:
            raw = self.base * (self.factor**retry)
        return min(raw, self.max_delay)
