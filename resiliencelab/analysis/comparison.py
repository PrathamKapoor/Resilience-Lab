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
    cohens_d,
    paired_difference_summary,
    small_sample_note,
    summarize,
)

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
    metrics_per_run: Iterable[dict[str, Any]], name: str, confidence: float = 0.95
) -> dict[str, Any]:
    values = [m[name] for m in metrics_per_run if name in m and m[name] is not None]
    summary_raw = summarize(values, confidence)
    summary: dict[str, Any] = dict(summary_raw)
    summary["n"] = summary.get("count", 0.0)
    summary["method"] = "t_mean_ci"
    summary["resampling_unit"] = "repetition"
    summary["analysis_version"] = STAT_ANALYSIS_VERSION
    summary["warnings"] = small_sample_note(int(summary["n"]))
    return summary


def _pair_metric(
    a_runs: list[dict[str, Any]], b_runs: list[dict[str, Any]], metric: str
) -> dict[str, Any]:
    n = min(len(a_runs), len(b_runs))
    avals = [m[metric] for m in a_runs[:n] if metric in m]
    bvals = [m[metric] for m in b_runs[:n] if metric in m]
    result_raw = paired_difference_summary(avals, bvals)
    result: dict[str, Any] = dict(result_raw)
    result["analysis_version"] = STAT_ANALYSIS_VERSION
    result["method"] = "paired_replicate"
    result["resampling_unit"] = "repetition"
    result["warnings"] = small_sample_note(int(result.get("n", 0)))
    return result


def build_comparison(
    experiments: list[dict[str, Any]],
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    metrics = metrics or PRIMARY_METRICS
    rows: dict[str, dict[str, Any]] = {}
    for experiment in experiments:
        name = experiment.get("name", experiment.get("id", "unknown"))
        per_run = experiment.get("metrics_per_run", [])
        row: dict[str, Any] = {"name": name, "id": experiment.get("id")}
        for metric in metrics:
            row[metric] = aggregate_metric(per_run, metric)
        rows[name] = row

    comparison: dict[str, Any] = {
        "analysis_version": STAT_ANALYSIS_VERSION,
        "paired": False,
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
                a = [m[metric] for m in ref_runs if metric in m]
                b = [m[metric] for m in other_runs if metric in m]
                n = min(len(a), len(b))
                if n >= 2:
                    entry[f"{metric}_cohens_d"] = cohens_d(a[:n], b[:n])
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
    for metric in metrics:
        result["metrics"][metric] = _pair_metric(a_runs, b_runs, metric)
    return result


def mean_ci_dict(values: list[float], confidence: float = 0.95) -> dict[str, float]:
    return summarize(values, confidence)
