"""Simulated service processing latency: pure, seeded delay sampling."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from resiliencelab.core.schema import ProcessingSpec
from resiliencelab.faults.model import LatencyDistribution

if TYPE_CHECKING:
    from numpy.random import Generator


def sample_processing_latency(spec: ProcessingSpec | None, rng: Generator) -> float:
    """Return the simulated processing delay for one request, in seconds.

    Deterministic when ``rng`` is seeded. Distribution semantics:

    - ``constant``  → ``mean``
    - ``uniform``   → ``U(min, max)`` if ``max > min``, else ``U(mean-σ, mean+σ)``
    - ``normal``    → ``max(0, N(mean, σ))``
    - ``lognormal`` → ``LogNormal(mean, σ)``
    - ``pareto``    → ``Pareto(2) + min``
    """
    if spec is None:
        return 0.0
    if spec.distribution is LatencyDistribution.CONSTANT:
        return spec.mean
    if spec.distribution is LatencyDistribution.UNIFORM:
        if spec.max > spec.min:
            return float(rng.uniform(spec.min, spec.max))
        low = max(0.0, spec.mean - spec.std)
        high = spec.mean + spec.std
        return float(rng.uniform(low, high))
    if spec.distribution is LatencyDistribution.NORMAL:
        return max(0.0, float(rng.normal(spec.mean, spec.std)))
    if spec.distribution is LatencyDistribution.LOGNORMAL:
        return float(rng.lognormal(mean=math.log(max(spec.mean, 1e-9)), sigma=spec.std))
    if spec.distribution is LatencyDistribution.PARETO:
        return float(rng.pareto(2.0)) + spec.min
    return 0.0
