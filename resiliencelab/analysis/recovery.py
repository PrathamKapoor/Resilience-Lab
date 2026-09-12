"""Recovery phase detection against explicit, configurable definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecoveryReport:
    baseline_throughput: float = 0.0
    degraded_at: float | None = None
    recovered_at: float | None = None
    time_to_degradation: float = 0.0
    time_to_recovery: float = 0.0
    degraded_duration: float = 0.0
    degraded: bool = False


def detect_recovery(
    throughput_series: list[tuple[float, float]],
    *,
    latency_series: list[tuple[float, float]] | None = None,
    baseline_window: float = 10.0,
    availability_threshold: float = 0.9,
    latency_tolerance: float = 0.25,
    stability_window: float = 5.0,
    latency_ratio: float = 2.0,
) -> RecoveryReport:
    report = RecoveryReport()
    series = sorted(throughput_series)
    if len(series) < 3:
        return report

    baseline_points = [(t, r) for t, r in series if t <= baseline_window] or series[:3]
    report.baseline_throughput = sum(r for _, r in baseline_points) / len(baseline_points)

    degrade_ratio = availability_threshold
    if report.baseline_throughput <= 0:
        return report

    degrade_at: float | None = None
    for t, r in series:
        if r < degrade_ratio * report.baseline_throughput:
            degrade_at = t
            break
    if degrade_at is None:
        return report

    report.degraded = True
    report.degraded_at = degrade_at
    report.time_to_degradation = degrade_at

    recover_at = _first_sustained_recovery(
        series,
        baseline=report.baseline_throughput,
        ratio=availability_threshold,
        stability_window=stability_window,
        after=degrade_at,
    )
    if recover_at is not None:
        report.recovered_at = recover_at
        report.time_to_recovery = recover_at - degrade_at
        report.degraded_duration = recover_at - degrade_at
    else:
        report.time_to_recovery = float("inf")
        report.degraded_duration = series[-1][0] - degrade_at
    return report


def _first_sustained_recovery(
    series: list[tuple[float, float]],
    *,
    baseline: float,
    ratio: float,
    stability_window: float,
    after: float,
) -> float | None:
    for i, (t, r) in enumerate(series):
        if t < after:
            continue
        if r < ratio * baseline:
            continue
        sustaining = all(
            rr >= ratio * baseline for tt, rr in series[i:] if tt <= t + stability_window
        )
        if sustaining:
            return t
    return None
