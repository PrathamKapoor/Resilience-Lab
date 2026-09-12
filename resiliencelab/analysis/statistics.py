"""Research-grade statistical helpers: CIs, effect sizes, summaries."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from scipy import stats

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
