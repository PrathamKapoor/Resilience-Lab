"""Timeout configuration and deadline propagation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Timeout:
    connect: float | None = None
    read: float | None = None
    total: float | None = None

    def __post_init__(self) -> None:
        for name in ("connect", "read", "total"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"timeout {name} must be positive or None")

    def combined(self, other: Timeout) -> Timeout:
        def merge(a: float | None, b: float | None) -> float | None:
            if a is None:
                return b
            if b is None:
                return a
            return min(a, b)

        return Timeout(
            connect=merge(self.connect, other.connect),
            read=merge(self.read, other.read),
            total=merge(self.total, other.total),
        )
