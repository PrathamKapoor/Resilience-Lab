"""Cross-experiment comparison with uncertainty and effect sizes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from resiliencelab.analysis.statistics import cohens_d, summarize, welch_ttest

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


def aggregate_metric(metrics_per_run: Iterable[dict[str, Any]], name: str) -> dict[str, float]:
    values = [m[name] for m in metrics_per_run if name in m and m[name] is not None]
    return summarize(values)


def build_comparison(
    experiments: list[dict[str, Any]],
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    metrics = metrics or PRIMARY_METRICS
    rows: dict[str, dict[str, Any]] = {}
    for experiment in experiments:
        name = experiment.get("name", experiment.get("id", "unknown"))
        per_run = experiment.get("metrics_per_run", [])
        row: dict[str, Any] = {"name": name}
        for metric in metrics:
            row[metric] = aggregate_metric(per_run, metric)
        rows[name] = row

    comparison: dict[str, Any] = {"experiments": list(rows.values())}

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
                if len(a) >= 2 and len(b) >= 2:
                    entry[f"{metric}_cohens_d"] = cohens_d(a, b)
                    _, p = welch_ttest(a, b)
                    entry[f"{metric}_p"] = p
            effects.append(entry)
        comparison["effects"] = effects

    return comparison


def mean_ci_dict(values: list[float], confidence: float = 0.95) -> dict[str, float]:
    data = summarize(values, confidence)
    return data
