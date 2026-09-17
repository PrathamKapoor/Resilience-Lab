"""Research-grade statistical helpers: CIs, effect sizes, summaries."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats

STAT_ANALYSIS_VERSION = "2"

Stat = Callable[[np.ndarray], float]


def summarize(values: list[float], confidence: float = 0.95) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return {"count": 0.0}
    lo, hi = mean_ci(arr, confidence)
    with np.errstate(invalid="ignore"):
        return {
            "count": float(arr.size),
            "mean": float(arr.mean()),
            "median": float(np.median(arr)),
            "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
            "variance": float(arr.var(ddof=1)) if arr.size > 1 else 0.0,
            "ci_low": float(lo),
            "ci_high": float(hi),
        }


def _is_finite_number(value: float) -> bool:
    """True only for finite numbers (excludes inf, -inf, and nan)."""
    return value == value and value != float("inf") and value != float("-inf")


def summarize_censored(values: list[float], confidence: float = 0.95) -> dict[str, float | str]:
    """Censoring-aware summary for metrics that may contain ``inf`` (unrecovered).

    Finite values are summarized normally; ``inf``/``nan`` entries count toward
    ``n``/``recovery_rate`` but never enter means or CIs, so one unrecovered
    run cannot poison an interval into ``nan``.

    All-censored input reports no mean/median/CI (explicit ``note``) rather
    than ``mean=inf``; empty input preserves the no-data shape.
    """
    arr = np.asarray(values, dtype=float)
    n = int(arr.size)
    if n == 0:
        return {
            "count": 0.0,
            "n_recovered": 0.0,
            "recovery_rate": 0.0,
            "note": "no data",
        }
    finite = [float(v) for v in arr.tolist() if _is_finite_number(float(v))]
    recovered = len(finite)
    base: dict[str, float | str] = {
        "count": float(n),
        "n_recovered": float(recovered),
        "recovery_rate": (recovered / n) if n else 0.0,
    }
    if not finite:
        base.update(
            {
                "n": float(n),
                "note": f"no recovered runs (all {n} censored/unrecovered)",
            }
        )
        return base
    summary = summarize(finite, confidence)
    base.update(summary)
    base["count"] = float(n)
    base["n"] = float(n)
    if recovered < n:
        base["note"] = f"{n - recovered}/{n} unrecovered (inf excluded from mean/CI)"
    return base


def mean_ci(values: np.ndarray, confidence: float = 0.95) -> tuple[float, float]:
    n = len(values)
    with np.errstate(invalid="ignore"):
        mean = float(values.mean())
        if n < 2:
            return mean, mean
        se = float(values.std(ddof=1) / math.sqrt(n))
    t = stats.t.ppf((1 + confidence) / 2, df=n - 1)
    return mean - t * se, mean + t * se


def bootstrap_ci(
    values: list[float],
    confidence: float = 0.95,
    resamples: int = 4000,
    rng: np.random.Generator | None = None,
    stat: Stat = np.mean,
) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0, 0.0
    rng = rng or np.random.default_rng(0)
    estimates = [
        float(stat(rng.choice(arr, size=arr.size, replace=True))) for _ in range(resamples)
    ]
    return (
        float(np.percentile(estimates, (1 - confidence) / 2 * 100)),
        float(np.percentile(estimates, (1 + confidence) / 2 * 100)),
    )


def cohens_d(a: list[float], b: list[float]) -> float:
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if x.size < 2 or y.size < 2:
        return 0.0
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        return float("nan")
    nx, ny = x.size, y.size
    pooled = math.sqrt(((nx - 1) * x.var(ddof=1) + (ny - 1) * y.var(ddof=1)) / (nx + ny - 2))
    if pooled == 0:
        return 0.0
    return float((x.mean() - y.mean()) / pooled)


def welch_ttest(a: list[float], b: list[float]) -> tuple[float, float]:
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if x.size < 2 or y.size < 2:
        return float("nan"), float("nan")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        return float("nan"), float("nan")
    t, p = stats.ttest_ind(x, y, equal_var=False)
    return float(t), float(p)


def cohens_d_paired(a: list[float], b: list[float]) -> float:
    """Paired effect size (Cohen's d_z): mean difference over SD of differences."""
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    n = min(x.size, y.size)
    if n < 2:
        return 0.0
    if not np.all(np.isfinite(x[:n])) or not np.all(np.isfinite(y[:n])):
        return float("nan")
    diffs = x[:n] - y[:n]
    sd = float(diffs.std(ddof=1))
    if sd == 0:
        return 0.0
    return float(diffs.mean() / sd)


def paired_difference_summary(
    a: list[float], b: list[float], confidence: float = 0.95
) -> dict[str, float | str]:
    """Paired-difference summary over matched replicate observations.

    Pairs by position (replicate index). The confidence interval is a t-based
    CI on the per-replicate differences — the correct unit for paired designs.

    Censored pairs (either side ``inf``/``nan``) never enter arithmetic means:
    the summary is computed over recovered pairs only, with explicit
    ``n_paired_recovered``/``n_censored_pairs`` counts. All-censored input
    reports no mean/CI rather than ``inf``/``nan``.
    """
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    n = min(x.size, y.size)
    if n == 0:
        return {"n": 0.0}
    a_vals = [float(v) for v in x[:n].tolist()]
    b_vals = [float(v) for v in y[:n].tolist()]
    a_rec: list[float] = []
    b_rec: list[float] = []
    n_censored = 0
    for av, bv in zip(a_vals, b_vals, strict=True):
        if _is_finite_number(av) and _is_finite_number(bv):
            a_rec.append(av)
            b_rec.append(bv)
        else:
            n_censored += 1
    if n_censored == 0:
        diffs = x[:n] - y[:n]
        lo, hi = mean_ci(diffs, confidence)
        return {
            "n": float(n),
            "mean_difference": float(diffs.mean()),
            "median_difference": float(np.median(diffs)),
            "ci_low": lo,
            "ci_high": hi,
            "cohens_d_paired": cohens_d_paired(list(x[:n]), list(y[:n])),
        }
    if not a_rec:
        return {
            "n": float(n),
            "n_paired_recovered": 0.0,
            "n_censored_pairs": float(n_censored),
            "note": f"no recovered pairs (all {n} censored/unrecovered)",
        }
    diffs_rec = np.asarray([av - bv for av, bv in zip(a_rec, b_rec, strict=True)], dtype=float)
    lo, hi = mean_ci(diffs_rec, confidence)
    return {
        "n": float(n),
        "n_paired_recovered": float(len(a_rec)),
        "n_censored_pairs": float(n_censored),
        "mean_difference": float(diffs_rec.mean()),
        "median_difference": float(np.median(diffs_rec)),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "cohens_d_paired": cohens_d_paired(a_rec, b_rec),
        "note": f"{n_censored}/{n} censored pairs excluded (inf); summary over recovered pairs only",
    }


def holm_adjust(pvalues: list[float]) -> list[float]:
    """Holm-Bonferroni step-down adjusted p-values (original order)."""
    if not pvalues:
        return []
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    previous = 0.0
    for rank, idx in enumerate(order):
        previous = max(previous, min(1.0, (m - rank) * pvalues[idx]))
        adjusted[idx] = previous
    return adjusted


def pareto_frontier(points: list[dict[str, float]], objectives: dict[str, bool]) -> list[int]:
    """Indices of Pareto-non-dominated points.

    ``objectives`` maps metric name to ``True`` (higher better) or ``False``
    (lower better). A point is dominated when another is no worse on every
    objective and strictly better on at least one. Inputs must be finite.
    """
    keys = list(objectives.keys())
    if not keys or not points:
        return []

    def dominates(i: int, j: int) -> bool:
        strictly = False
        for key in keys:
            vi = points[i][key]
            vj = points[j][key]
            higher = objectives[key]
            if higher:
                if vi < vj:
                    return False
                if vi > vj:
                    strictly = True
            else:
                if vi > vj:
                    return False
                if vi < vj:
                    strictly = True
        return strictly

    return [
        i
        for i in range(len(points))
        if not any(j != i and dominates(j, i) for j in range(len(points)))
    ]


def small_sample_note(n: int) -> list[str]:
    notes: list[str] = []
    if n < 2:
        notes.append("n<2: descriptive only; no inferential CI or effect size")
    elif n < 5:
        notes.append("n<5: highly uncertain; treat intervals/effect sizes cautiously")
    return notes


@dataclass
class StatisticalResult:
    """Structured, serializable, versioned statistical result."""

    metric: str
    estimate: float
    n: int
    method: str = "t_mean_ci"
    confidence_level: float = 0.95
    ci_low: float | None = None
    ci_high: float | None = None
    paired: bool = False
    reference: float | None = None
    difference: float | None = None
    effect_size: float | None = None
    effect_size_method: str | None = None
    resampling_unit: str = "repetition"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_version": STAT_ANALYSIS_VERSION,
            "metric": self.metric,
            "estimate": self.estimate,
            "n": self.n,
            "method": self.method,
            "confidence_level": self.confidence_level,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "paired": self.paired,
            "reference": self.reference,
            "difference": self.difference,
            "effect_size": self.effect_size,
            "effect_size_method": self.effect_size_method,
            "resampling_unit": self.resampling_unit,
            "warnings": self.warnings,
        }
