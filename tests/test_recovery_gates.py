"""C5 regression: recovery requires ALL evaluated gates for the stability window."""

from __future__ import annotations

from resiliencelab.analysis.recovery import detect_recovery


def _throughput() -> list[tuple[float, float]]:
    healthy = [(float(t), 100.0) for t in range(5)]
    degraded = [(5.0, 10.0)]
    recovered = [(float(t), 100.0) for t in range(6, 20)]
    return healthy + degraded + recovered


def _latency_good() -> list[tuple[float, float]]:
    return [(float(t), 0.05) for t in range(20)]


def _latency_bad() -> list[tuple[float, float]]:
    return [(float(t), 0.05) for t in range(5)] + [(float(t), 5.0) for t in range(5, 20)]


def test_throughput_recovers_but_p95_does_not_is_not_recovered() -> None:
    report = detect_recovery(
        _throughput(),
        latency_series=_latency_bad(),
        baseline_window=4.0,
        availability_threshold=0.9,
        stability_window=2.0,
    )
    assert report.degraded
    assert "latency" in report.gates_evaluated
    assert report.latency_degraded is True
    assert report.recovered_at is None
    assert report.time_to_recovery == float("inf")
    assert report.latency_recovered is False


def test_p95_recovers_but_throughput_does_not_is_not_recovered() -> None:
    degraded = [(float(t), 100.0) for t in range(5)] + [(float(t), 10.0) for t in range(5, 20)]
    report = detect_recovery(
        degraded,
        latency_series=_latency_good(),
        baseline_window=4.0,
        availability_threshold=0.9,
        stability_window=2.0,
    )
    assert report.degraded
    assert report.recovered_at is None
    assert report.time_to_recovery == float("inf")


def test_both_recover_is_recovered_with_gates_persisted() -> None:
    report = detect_recovery(
        _throughput(),
        latency_series=_latency_good(),
        baseline_window=4.0,
        availability_threshold=0.9,
        stability_window=2.0,
    )
    assert report.degraded
    assert report.recovered_at is not None
    assert report.time_to_recovery != float("inf")
    assert report.gates_evaluated == ["throughput", "latency"]
    assert report.baseline_p95_latency > 0
    assert report.latency_gate > 0
    assert report.latency_recovered is True


def test_stability_window_break_is_not_recovered() -> None:
    # Throughput recovers briefly then drops inside the stability window.
    series = (
        [(float(t), 100.0) for t in range(5)]
        + [(5.0, 10.0), (6.0, 100.0), (7.0, 10.0)]
        + [(float(t), 100.0) for t in range(8, 20)]
    )
    report = detect_recovery(
        series,
        latency_series=_latency_good(),
        baseline_window=4.0,
        availability_threshold=0.9,
        stability_window=3.0,
    )
    assert report.degraded
    # First sustained recovery satisfying BOTH gates across the full window.
    assert report.recovered_at is not None
    assert report.recovered_at >= 8.0


def test_throughput_only_without_latency_series() -> None:
    report = detect_recovery(
        _throughput(),
        baseline_window=4.0,
        availability_threshold=0.9,
        stability_window=2.0,
    )
    assert report.degraded
    assert report.recovered_at is not None
    assert report.gates_evaluated == ["throughput"]
