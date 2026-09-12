"""Interaction-effect analysis between resilience mechanisms."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from resiliencelab.analysis.statistics import bootstrap_ci


def two_way_interaction(
    a_off_b_off: Iterable[float],
    a_on_b_off: Iterable[float],
    a_off_b_on: Iterable[float],
    a_on_b_on: Iterable[float],
) -> dict[str, float]:
    """Classic 2x2 difference-of-differences interaction estimate."""
    a_off_b_off = list(a_off_b_off)
    a_on_b_off = list(a_on_b_off)
    a_off_b_on = list(a_off_b_on)
    a_on_b_on = list(a_on_b_on)

    def mean(v: list[float]) -> float:
        return float(np.mean(v)) if v else 0.0

    effect_a_given_b_off = mean(a_on_b_off) - mean(a_off_b_off)
    effect_a_given_b_on = mean(a_on_b_on) - mean(a_off_b_on)
    interaction = effect_a_given_b_on - effect_a_given_b_off

    return {
        "effect_a_with_b_off": effect_a_given_b_off,
        "effect_a_with_b_on": effect_a_given_b_on,
        "interaction": interaction,
    }


def interaction_with_uncertainty(
    a_off_b_off: list[float],
    a_on_b_off: list[float],
    a_off_b_on: list[float],
    a_on_b_on: list[float],
    *,
    resamples: int = 4000,
) -> dict[str, float]:
    result = two_way_interaction(a_off_b_off, a_on_b_off, a_off_b_on, a_on_b_on)

    grouped = list(a_off_b_off) + list(a_on_b_off) + list(a_off_b_on) + list(a_on_b_on)
    if grouped:
        rng = np.random.default_rng(0)
        larger = max(len(a_off_b_off), len(a_on_b_off), len(a_off_b_on), len(a_on_b_on))
        deltas: list[float] = []
        for _ in range(resamples):
            aa = _resample(rng, a_off_b_off, larger)
            ab = _resample(rng, a_on_b_off, larger)
            ba = _resample(rng, a_off_b_on, larger)
            bb = _resample(rng, a_on_b_on, larger)
            dod = two_way_interaction(aa, ab, ba, bb)["interaction"]
            deltas.append(dod)
        result["interaction_ci_low"], result["interaction_ci_high"] = bootstrap_ci(
            deltas, resamples=1
        )
    return result


def _resample(rng: np.random.Generator, values: list[float], size: int) -> list[float]:
    if not values:
        return [0.0] * max(size, 1)
    arr = np.asarray(values, dtype=float)
    sampled: list[float] = list(rng.choice(arr, size=size, replace=True).tolist())
    return sampled
