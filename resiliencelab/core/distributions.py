"""Shared statistical sampling helpers used by faults and workloads."""

from __future__ import annotations

import math
from typing import Protocol


class Rng(Protocol):
    def uniform(self, low: float, high: float) -> float: ...
    def normal(self, loc: float, scale: float) -> float: ...
    def pareto(self, a: float) -> float: ...


def sample_uniform(rng: Rng, low: float, high: float) -> float:
    return rng.uniform(low, high)


def sample_normal(rng: Rng, mean: float, std: float) -> float:
    return max(0.0, rng.normal(mean, std))


def sample_lognormal(rng: Rng, mean: float, sigma: float) -> float:
    return (
        float(rng.lognormal(mean=math.log(max(mean, 1e-9)), sigma=sigma))
        if hasattr(rng, "lognormal")
        else math.exp(rng.normal(math.log(max(mean, 1e-9)), sigma))
    )


def sample_pareto(rng: Rng, shape: float) -> float:
    return (
        float(rng.pareto(shape))
        if hasattr(rng, "pareto")
        else 1.0 / (1.0 - rng.uniform(0.0, 1.0)) ** (1.0 / shape)
    )
