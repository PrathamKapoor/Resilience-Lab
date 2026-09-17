"""Cross-experiment comparison with uncertainty and effect sizes.

Observations are **repetition-level** metrics (one value per seeded run), never
request-level. ``build_comparison`` produces independent-group summaries;
``build_paired_comparison`` produces matched-replicate summaries keyed by
replicate index.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from resiliencelab.analysis.statistics import (
    STAT_ANALYSIS_VERSION,
    bootstrap_ci,
    cohens_d,
    paired_difference_summary,
    small_sample_note,
    summarize,
    summarize_censored,
)


def _has_censored(values: list[float]) -> bool:
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f == float("inf") or f == float("-inf"):
            return True
    return False


def _recovery_rates(values: list[float]) -> tuple[int, int, float]:
    finite = 0
    total = 0
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        total += 1
        if f == f and f != float("inf") and f != float("-inf"):
            finite += 1
    rate = (finite / total) if total else 0.0
    return finite, total, rate


PRIMARY_METRICS = [
    "availability",
    "throughput",
    "latency_mean",
    "latency_p95",
    "latency_p99",
    "amplification",
    "recovery_time",
    "error_rate",
    "timeout_rate",
]


def aggregate_metric(
    metrics_per_run: Iterable[dict[str, Any]],
    name: str,
    confidence: float = 0.95,
    use_bootstrap: bool = False,
) -> dict[str, Any]:
    """Aggregate repetition-level values with one coherent recovery definition.

    ``recovery_time`` uses censored semantics whenever any run is censored
    (``inf``/``nan``): ordinary means are never computed from values containing
    ``inf``. All-recovered recovery input uses the ordinary summary; mixed
    input uses the censored summary over recovered runs; all-censored input
    reports an explicit censored result with no mean/CI; empty input preserves
    the no-data shape.
    """
    values = [m[name] for m in metrics_per_run if name in m and m[name] is not None]
    if not values:
        return {"n": 0.0}
    if name == "recovery_time" and _has_censored([float(v) for v in values]):
        censored: dict[str, Any] = dict(summarize_censored([float(v) for v in values], confidence))
        censored["method"] = "censored_t_mean_ci"
        censored["resampling_unit"] = "repetition"
        censored["analysis_version"] = STAT_ANALYSIS_VERSION
        try:
            n_warn = int(censored.get("n_recovered", censored.get("count", 0)))
        except (TypeError, ValueError):
            n_warn = 0
        censored["warnings"] = small_sample_note(n_warn)
        censored["n"] = censored.get("count", 0.0)
        return censored
    if use_bootstrap and len(values) >= 3:
        lo, hi = bootstrap_ci(values, confidence)
        mean_val = sum(values) / len(values)
        summary: dict[str, Any] = {
            "n": float(len(values)),
            "mean": mean_val,
            "median": sorted(values)[len(values) // 2],
            "ci_low": lo,
            "ci_high": hi,
            "method": "bootstrap",
            "resampling_unit": "repetition",
            "analysis_version": STAT_ANALYSIS_VERSION,
            "warnings": small_sample_note(len(values)),
        }
    else:
        summary_raw = summarize(values, confidence)
        summary = dict(summary_raw)
        summary["method"] = "t_mean_ci"
        summary["resampling_unit"] = "repetition"
        summary["analysis_version"] = STAT_ANALYSIS_VERSION
        summary["warnings"] = small_sample_note(int(summary.get("count", 0)))
    summary["n"] = summary.get("count", 0.0)
    return summary


def _pair_metric(
    a_runs: list[dict[str, Any]], b_runs: list[dict[str, Any]], metric: str
) -> dict[str, Any]:
    n = min(len(a_runs), len(b_runs))
    avals = [m[metric] for m in a_runs[:n] if metric in m and m[metric] is not None]
    bvals = [m[metric] for m in b_runs[:n] if metric in m and m[metric] is not None]
    result_raw = paired_difference_summary(avals, bvals)
    result: dict[str, Any] = dict(result_raw)
    result["analysis_version"] = STAT_ANALYSIS_VERSION
    result["method"] = "paired_replicate"
    result["resampling_unit"] = "repetition"
    try:
        n_warn = int(result.get("n_paired_recovered", result.get("n", 0)))
    except (TypeError, ValueError):
        n_warn = 0
    result["warnings"] = small_sample_note(n_warn)
    return result


def build_comparison(
    experiments: list[dict[str, Any]],
    metrics: list[str] | None = None,
    confidence: float = 0.95,
) -> dict[str, Any]:
    metrics = metrics or PRIMARY_METRICS
    rows: dict[str, dict[str, Any]] = {}
    for experiment in experiments:
        name = experiment.get("name", experiment.get("id", "unknown"))
        per_run = experiment.get("metrics_per_run", [])
        row: dict[str, Any] = {"name": name, "id": experiment.get("id")}
        for metric in metrics:
            row[metric] = aggregate_metric(per_run, metric, confidence)
        rows[name] = row

    comparison: dict[str, Any] = {
        "analysis_version": STAT_ANALYSIS_VERSION,
        "paired": False,
        "confidence_level": confidence,
        "experiments": list(rows.values()),
    }

    if len(experiments) >= 2:
        reference = experiments[0]
        effects: list[dict[str, Any]] = []
        ref_runs = reference.get("metrics_per_run", [])
        for other in experiments[1:]:
            other_runs = other.get("metrics_per_run", [])
            entry: dict[str, Any] = {"versus": other.get("name", other.get("id"))}
            for metric in metrics:
                a = [m[metric] for m in ref_runs if metric in m and m[metric] is not None]
                b = [m[metric] for m in other_runs if metric in m and m[metric] is not None]
                n = min(len(a), len(b))
                if metric == "recovery_time" and (
                    _has_censored([float(v) for v in a[:n]])
                    or _has_censored([float(v) for v in b[:n]])
                ):
                    entry[f"{metric}_cohens_d"] = None
                    entry[f"{metric}_cohens_d_note"] = (
                        "censored: Cohen's d undefined with unrecovered runs (inf); "
                        "compare recovery_rate and recovered-only means instead"
                    )
                    a_rec, a_tot, a_rate = _recovery_rates([float(v) for v in a[:n]])
                    b_rec, b_tot, b_rate = _recovery_rates([float(v) for v in b[:n]])
                    entry[f"{metric}_recovery_rate_a"] = a_rate
                    entry[f"{metric}_recovery_rate_b"] = b_rate
                    entry[f"{metric}_n_recovered_a"] = a_rec
                    entry[f"{metric}_n_recovered_b"] = b_rec
                elif n >= 2:
                    d = cohens_d(a[:n], b[:n])
                    # Never propagate nan/inf into comparison JSON.
                    if d != d or d == float("inf") or d == float("-inf"):
                        entry[f"{metric}_cohens_d"] = None
                        entry[f"{metric}_cohens_d_note"] = (
                            "effect undefined for non-finite inputs; no number fabricated"
                        )
                    else:
                        entry[f"{metric}_cohens_d"] = d
                entry[f"{metric}_n"] = n
            effects.append(entry)
        comparison["effects"] = effects

    return comparison


def build_paired_comparison(
    a: dict[str, Any],
    b: dict[str, Any],
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    metrics = metrics or PRIMARY_METRICS
    a_runs = a.get("metrics_per_run", [])
    b_runs = b.get("metrics_per_run", [])
    n = min(len(a_runs), len(b_runs))
    result: dict[str, Any] = {
        "analysis_version": STAT_ANALYSIS_VERSION,
        "method": "paired_replicate",
        "paired": True,
        "reference": a.get("name", a.get("id")),
        "versus": b.get("name", b.get("id")),
        "n_a": len(a_runs),
        "n_b": len(b_runs),
        "n_matched": n,
        "metrics": {},
        "warnings": [],
    }
    if len(a_runs) != len(b_runs):
        result["warnings"].append(
            f"unbalanced replicates (a={len(a_runs)}, b={len(b_runs)}); paired by first {n}"
        )
    seeds_a = a.get("seeds")
    seeds_b = b.get("seeds")
    if (
        isinstance(seeds_a, list)
        and isinstance(seeds_b, list)
        and seeds_a
        and seeds_b
        and list(seeds_a[:n]) != list(seeds_b[:n])
    ):
        result["warnings"].append(
            "seeds differ between conditions; paired comparison pairs by replicate "
            "index, which is valid only when index i shares stochastic conditions"
        )
    for metric in metrics:
        result["metrics"][metric] = _pair_metric(a_runs, b_runs, metric)
    return result


def mean_ci_dict(values: list[float], confidence: float = 0.95) -> dict[str, float]:
    return summarize(values, confidence)
