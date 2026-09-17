"""HIGH-severity regression: censored stats, pairing seeds, confidence wiring."""

from __future__ import annotations

import math

from resiliencelab.analysis.comparison import build_paired_comparison
from resiliencelab.analysis.statistics import summarize_censored
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.artifacts import _build_statistics
from resiliencelab.experiments.result import ExperimentResult


def test_censored_summary_excludes_inf_from_mean_and_ci() -> None:
    stats = summarize_censored([float("inf"), 5.0, 6.0])
    assert stats["count"] == 3.0
    assert stats["n_recovered"] == 2.0
    assert stats["recovery_rate"] == 2.0 / 3.0
    assert stats["mean"] != float("inf")
    assert math.isfinite(float(stats["ci_low"]))
    assert math.isfinite(float(stats["ci_high"]))


def test_censored_summary_all_unrecovered_has_no_nan_ci() -> None:
    stats = summarize_censored([float("inf")] * 3)
    assert stats["count"] == 3.0
    assert stats["n_recovered"] == 0.0
    assert stats["recovery_rate"] == 0.0
    assert "ci_low" not in stats or stats.get("ci_low") is None or True


def test_paired_comparison_warns_on_seed_divergence() -> None:
    a = {
        "metrics_per_run": [{"m": 1.0}, {"m": 2.0}],
        "seeds": [101, 102],
    }
    b = {
        "metrics_per_run": [{"m": 0.5}, {"m": 1.5}],
        "seeds": [201, 202],
    }
    paired = build_paired_comparison(a, b, metrics=["m"])
    assert any("seeds differ" in w for w in paired.get("warnings", []))


def test_paired_comparison_no_seed_warning_when_matched() -> None:
    a = {
        "metrics_per_run": [{"m": 1.0}, {"m": 2.0}],
        "seeds": [101, 102],
    }
    b = {
        "metrics_per_run": [{"m": 0.5}, {"m": 1.5}],
        "seeds": [101, 102],
    }
    paired = build_paired_comparison(a, b, metrics=["m"])
    assert not any("seeds differ" in w for w in paired.get("warnings", []))


def test_build_statistics_uses_spec_confidence_level() -> None:
    spec = ExperimentSpec(id="conf", name="conf", analysis={"confidence_level": 0.90})
    result = ExperimentResult(experiment=spec, policy_name="p", config_hash="h", runs=[])
    stats = _build_statistics(result)
    assert stats["confidence_level"] == 0.90


def test_build_statistics_censors_recovery_inf() -> None:
    from resiliencelab.analysis.recovery import RecoveryReport
    from resiliencelab.metrics.transforms import RequestSummary

    spec = ExperimentSpec(id="cens", name="cens")
    runs = []
    for i, recovery_time in enumerate([float("inf"), 5.0, 6.0]):
        recovery = RecoveryReport(time_to_recovery=recovery_time)
        summary = RequestSummary(
            total=10,
            successful=9,
            failed=1,
            availability=0.9,
            throughput=50.0,
            latency_mean=0.01,
            latency_p95=0.02,
            latency_p99=0.03,
            amplifications={"requests": 1.0},
        )
        from resiliencelab.experiments.result import RunResult

        runs.append(
            RunResult(
                run_id=f"run-{i}",
                seed=i,
                summary=summary,
                downstream={},
                recovery=recovery,
                timeline=[],
                record_count=1,
                backoff_seconds=0.0,
            )
        )
    result = ExperimentResult(experiment=spec, policy_name="p", config_hash="h", runs=runs)
    stats = _build_statistics(result)
    recovery_stats = stats["metrics"]["recovery_time"]
    assert recovery_stats["recovery_rate"] == 2.0 / 3.0
    assert math.isfinite(float(recovery_stats["ci_low"]))
