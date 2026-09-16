from __future__ import annotations

import pytest

from resiliencelab.analysis.comparison import build_comparison
from resiliencelab.analysis.recovery import detect_recovery
from resiliencelab.analysis.scoring import DEFAULT_WEIGHTS, compute_score
from resiliencelab.analysis.statistics import bootstrap_ci, cohens_d, summarize


def test_summarize_ci_ordering() -> None:
    stats = summarize([0.9, 0.92, 0.88, 0.91, 0.89])
    assert stats["ci_low"] <= stats["mean"] <= stats["ci_high"]
    assert stats["count"] == 5.0


def test_bootstrap_ci_ordering() -> None:
    lo, hi = bootstrap_ci([1.0, 2.0, 3.0, 4.0], resamples=200)
    assert lo <= hi


def test_cohens_d_sign() -> None:
    assert cohens_d([1.0, 1.1, 0.9], [0.0, 0.1, -0.1]) > 0
    assert cohens_d([0.0, 0.1, -0.1], [1.0, 1.1, 0.9]) < 0


def test_comparison_effect_sizes() -> None:
    a = {
        "id": "a",
        "name": "a",
        "metrics_per_run": [{"availability": v} for v in (0.9, 0.91, 0.89)],
    }
    b = {
        "id": "b",
        "name": "b",
        "metrics_per_run": [{"availability": v} for v in (0.5, 0.51, 0.49)],
    }
    comparison = build_comparison([a, b], metrics=["availability"])
    assert comparison["experiments"][0]["availability"]["mean"] == pytest.approx(0.9)
    assert comparison["effects"][0]["availability_cohens_d"] > 0


def test_recovery_detection() -> None:
    healthy = [(float(t), 100.0) for t in range(5)]
    degraded = [(float(t), 10.0) for t in range(5, 15)]
    recovered = [(float(t), 100.0) for t in range(15, 25)]
    report = detect_recovery(
        healthy + degraded + recovered,
        baseline_window=4.0,
        availability_threshold=0.9,
        stability_window=2.0,
    )
    assert report.degraded
    assert report.degraded_at == pytest.approx(5.0)
    assert report.recovered_at is not None and report.recovered_at >= 15.0


def test_recovery_never_degraded() -> None:
    series = [(float(t), 100.0) for t in range(20)]
    report = detect_recovery(series, baseline_window=5.0, availability_threshold=0.9)
    assert not report.degraded
    assert report.recovered_at is None


def test_recovery_never_recovers() -> None:
    healthy = [(float(t), 100.0) for t in range(5)]
    degraded = [(float(t), 10.0) for t in range(5, 25)]
    report = detect_recovery(
        healthy + degraded,
        baseline_window=4.0,
        availability_threshold=0.9,
        stability_window=2.0,
    )
    assert report.degraded
    assert report.recovered_at is None
    assert report.time_to_recovery == float("inf")


def test_recovery_insufficient_data() -> None:
    report = detect_recovery([(0.0, 100.0), (1.0, 90.0)])
    assert not report.degraded


def test_recovery_zero_baseline() -> None:
    series = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    report = detect_recovery(series, baseline_window=5.0)
    assert not report.degraded
    assert report.baseline_throughput == 0.0


def test_score_exposes_weights_and_range() -> None:
    score = compute_score(
        availability=0.99,
        throughput=90.0,
        reference_throughput=100.0,
        p99=0.05,
        reference_p99=0.05,
        error_rate=0.01,
        amplification=1.1,
        recovery_time=2.0,
        reference_recovery_time=10.0,
    )
    assert 0.0 <= score.score <= 1.0
    assert set(score.weights) == set(DEFAULT_WEIGHTS)
    assert score.components["availability"] == pytest.approx(0.99)
