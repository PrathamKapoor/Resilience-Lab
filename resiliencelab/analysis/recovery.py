"""Recovery phase detection against explicit, configurable definitions.

Recovery requires BOTH:
1. Throughput recovery: throughput >= availability_threshold * baseline_throughput
2. Latency recovery (if latency_series provided): p95 <= baseline_p95 * (1 + latency_tolerance)

Both conditions must be sustained for stability_window seconds.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecoveryReport:
    baseline_throughput: float = 0.0
    baseline_p95_latency: float = 0.0
    degraded_at: float | None = None
    recovered_at: float | None = None
    time_to_degradation: float = 0.0
    time_to_recovery: float = 0.0
    degraded_duration: float = 0.0
    degraded: bool = False
    latency_degraded: bool = False
    latency_recovered: bool = False


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

    # Compute baseline p95 latency if latency_series provided
    latency_baseline_points: list[float] = []
    if latency_series:
        sorted_latency = sorted(latency_series)
        latency_baseline_points = [r for t, r in sorted_latency if t <= baseline_window]
        if not latency_baseline_points:
            latency_baseline_points = [r for _, r in sorted_latency[:3]]
        if latency_baseline_points:
            report.baseline_p95_latency = sum(latency_baseline_points) / len(
                latency_baseline_points
            )

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
        latency_series=latency_series,
        baseline=report.baseline_throughput,
        baseline_p95=report.baseline_p95_latency,
        ratio=availability_threshold,
        latency_tolerance=latency_tolerance,
        latency_ratio=latency_ratio,
        stability_window=stability_window,
        after=degrade_at,
    )
    if recover_at is not None:
        report.recovered_at = recover_at
        report.time_to_recovery = recover_at - degrade_at
        report.degraded_duration = recover_at - degrade_at
        report.latency_recovered = True
    else:
        report.time_to_recovery = float("inf")
        report.degraded_duration = series[-1][0] - degrade_at
    return report


def _first_sustained_recovery(
    series: list[tuple[float, float]],
    *,
    latency_series: list[tuple[float, float]] | None,
    baseline: float,
    baseline_p95: float,
    ratio: float,
    latency_tolerance: float,
    latency_ratio: float,
    stability_window: float,
    after: float,
) -> float | None:
    for i, (t, r) in enumerate(series):
        if t < after:
            continue
        if r < ratio * baseline:
            continue

        # Check throughput recovery
        throughput_sustaining = all(
            rr >= ratio * baseline for tt, rr in series[i:] if tt <= t + stability_window
        )
        if not throughput_sustaining:
            continue

        # Check latency recovery if latency_series provided
        if latency_series and baseline_p95 > 0:
            latency_ok = _latency_recovery_sustained(
                latency_series,
                baseline_p95,
                latency_tolerance,
                latency_ratio,
                t,
                stability_window,
                after,
            )
            if not latency_ok:
                continue

        return t
    return None


def _latency_recovery_sustained(
    latency_series: list[tuple[float, float]],
    baseline_p95: float,
    latency_tolerance: float,
    latency_ratio: float,
    start_time: float,
    stability_window: float,
    after: float,
) -> bool:
    """Check if latency has sustained recovery from start_time."""
    sorted_latency = sorted(latency_series)
    max_latency = baseline_p95 * (1 + latency_tolerance) * latency_ratio
    for t, p95 in sorted_latency:
        if t < after:
            continue
        if t > start_time + stability_window:
            break
        if p95 > max_latency:
            return False
    return True
