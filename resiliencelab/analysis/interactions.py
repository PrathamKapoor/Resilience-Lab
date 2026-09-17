"""Interaction-effect analysis between resilience mechanisms."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def _finite_cell(values: list[float]) -> tuple[list[float], int, int]:
    import math

    finite: list[float] = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            finite.append(f)
    return finite, len(values), len(finite)


def two_way_interaction(
    a_off_b_off: Iterable[float],
    a_on_b_off: Iterable[float],
    a_off_b_on: Iterable[float],
    a_on_b_on: Iterable[float],
) -> dict[str, float | None | str | bool]:
    """Classic 2x2 difference-of-differences interaction estimate.

    Censored values (``inf``/``nan``) never enter arithmetic means: cell means
    are recovered-only means. When any cell has no recovered observations the
    interaction is ``None`` with an explicit note rather than a fabricated
    number or ``inf``/``nan``.
    """
    a_off_b_off = list(a_off_b_off)
    a_on_b_off = list(a_on_b_off)
    a_off_b_on = list(a_off_b_on)
    a_on_b_on = list(a_on_b_on)

    def censored_mean(v: list[float]) -> float | None:
        finite, _n, _r = _finite_cell([float(x) for x in v])
        if not finite:
            return None
        return float(np.mean(finite))

    m00 = censored_mean(a_off_b_off)
    m10 = censored_mean(a_on_b_off)
    m01 = censored_mean(a_off_b_on)
    m11 = censored_mean(a_on_b_on)
    if m00 is None or m10 is None or m01 is None or m11 is None:
        return {
            "effect_a_with_b_off": None,
            "effect_a_with_b_on": None,
            "interaction": None,
            "censored": True,
            "note": (
                "interaction undefined: at least one cell has no recovered "
                "observations (all censored/unrecovered)"
            ),
        }

    def mean(v: list[float]) -> float:
        finite, _n, _r = _finite_cell([float(x) for x in v])
        return float(np.mean(finite)) if finite else 0.0

    effect_a_given_b_off = mean(a_on_b_off) - mean(a_off_b_off)
    effect_a_given_b_on = mean(a_on_b_on) - mean(a_off_b_on)
    interaction = effect_a_given_b_on - effect_a_given_b_off

    result: dict[str, float | None | str | bool] = {
        "effect_a_with_b_off": effect_a_given_b_off,
        "effect_a_with_b_on": effect_a_given_b_on,
        "interaction": interaction,
    }
    _, n00, r00 = _finite_cell([float(x) for x in a_off_b_off])
    _, n10, r10 = _finite_cell([float(x) for x in a_on_b_off])
    _, n01, r01 = _finite_cell([float(x) for x in a_off_b_on])
    _, n11, r11 = _finite_cell([float(x) for x in a_on_b_on])
    if r00 < n00 or r10 < n10 or r01 < n01 or r11 < n11:
        result["censored"] = True
        result["note"] = "censored values (inf) excluded; recovered-only cell means"
    return result


def interaction_with_uncertainty(
    a_off_b_off: list[float],
    a_on_b_off: list[float],
    a_off_b_on: list[float],
    a_on_b_on: list[float],
    *,
    resamples: int = 4000,
) -> dict[str, float | None | str | bool]:
    result = two_way_interaction(a_off_b_off, a_on_b_off, a_off_b_on, a_on_b_on)
    if result.get("interaction") is None:
        return result

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
            if dod is None:
                continue
            try:
                deltas.append(float(dod))
            except (TypeError, ValueError):
                continue
        if deltas:
            import math as _math

            finite_deltas = [d for d in deltas if _math.isfinite(d)]
            if finite_deltas:
                result["interaction_ci_low"] = float(np.percentile(finite_deltas, 2.5))
                result["interaction_ci_high"] = float(np.percentile(finite_deltas, 97.5))
    return result


def _resample(rng: np.random.Generator, values: list[float], size: int) -> list[float]:
    if not values:
        return [0.0] * max(size, 1)
    arr = np.asarray(values, dtype=float)
    sampled: list[float] = list(rng.choice(arr, size=size, replace=True).tolist())
    return sampled
