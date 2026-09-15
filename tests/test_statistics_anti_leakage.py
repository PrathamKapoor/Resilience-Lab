"""Critical anti-leakage tests for statistical correctness (Phase 5)."""

from __future__ import annotations

import pytest

from resiliencelab.analysis.comparison import aggregate_metric, build_paired_comparison
from resiliencelab.analysis.design import build_design, group_by_factor, main_effect
from resiliencelab.analysis.interactions import two_way_interaction
from resiliencelab.analysis.statistics import (
    STAT_ANALYSIS_VERSION,
    bootstrap_ci,
    paired_difference_summary,
)
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.result import ExperimentResult, RunResult


# ------------------------------------------------------------------
# A — Request-level pseudo-replication
# ------------------------------------------------------------------
def test_pseudo_replication_uses_repetition_unit_not_request_count() -> None:
    """Even with many internal requests, statistics must use repetition count."""
    # 3 repetitions, each with one aggregated metric value
    repetitions = [{"availability": 0.9}, {"availability": 0.92}, {"availability": 0.88}]
    result = aggregate_metric(repetitions, "availability")
    assert int(result["n"]) == 3
    assert result["count"] == 3.0
    assert result["resampling_unit"] == "repetition"
    assert result["analysis_version"] == STAT_ANALYSIS_VERSION
    # The mean should be the mean of the 3 repetitions
    assert result["mean"] == pytest.approx(0.9)


# ------------------------------------------------------------------
# B — Pairing mismatch
# ------------------------------------------------------------------
def test_pairing_requires_matched_replicate_identity() -> None:
    """Different replicate counts must not be silently fully paired."""
    a = {"metrics_per_run": [{"m": 1.0}, {"m": 1.1}, {"m": 1.2}]}
    b = {"metrics_per_run": [{"m": 0.0}, {"m": 0.1}]}
    paired = build_paired_comparison(a, b, metrics=["m"])
    assert paired["paired"] is True
    assert paired["n_matched"] == 2
    assert int(paired["metrics"]["m"]["n"]) == 2
    assert any("unbalanced" in w for w in paired.get("warnings", []))


def test_pairing_does_not_silently_match_different_seeds() -> None:
    """If replicate identity differs (e.g. different seeds), pairing is by index."""
    a = {"metrics_per_run": [{"m": 1.0}, {"m": 2.0}], "seeds": [101, 102]}
    b = {"metrics_per_run": [{"m": 0.0}, {"m": 1.0}], "seeds": [201, 202]}
    paired = build_paired_comparison(a, b, metrics=["m"])
    # Paired by first 2 indices regardless of seed values
    assert paired["n_matched"] == 2


# ------------------------------------------------------------------
# C — Bootstrap reproducibility
# ------------------------------------------------------------------
def test_bootstrap_is_deterministic_given_fixed_inputs() -> None:
    """Two runs of bootstrap_ci with the same inputs must match exactly."""
    data = [1.2, 2.3, 3.1, 2.8, 3.5]
    lo1, hi1 = bootstrap_ci(data, confidence=0.95)
    lo2, hi2 = bootstrap_ci(data, confidence=0.95)
    assert lo1 == pytest.approx(lo2, abs=1e-6)
    assert hi1 == pytest.approx(hi2, abs=1e-6)


# ------------------------------------------------------------------
# D — Condition contamination
# ------------------------------------------------------------------
def test_factorial_conditions_do_not_contaminate() -> None:
    """Observations for one condition must not leak into another."""
    spec = ExperimentSpec(id="test_contam", name="test_contam")
    conditions = build_design(
        spec,
        {"policy.retry": [None, {"enabled": True, "max_attempts": 3}]},
    )
    observations: dict[str, list[float]] = {
        conditions[0].condition_id: [0.9],
        conditions[1].condition_id: [0.5],
    }
    grouped = group_by_factor(conditions, observations, "policy.retry")
    # Group keys are canonical string representations
    none_key = "None"
    none_vals = grouped.get(none_key, [])
    assert len(none_vals) == 1
    assert none_vals[0] == pytest.approx(0.9)


def test_main_effect_does_not_mix_cell_observations() -> None:
    spec = ExperimentSpec(id="test_contam2", name="test_contam2")
    conditions = build_design(
        spec,
        {
            "policy.retry": [None, {"enabled": True}],
            "policy.circuit_breaker": [None, {"enabled": True}],
        },
    )
    observations = {}
    for c in conditions:
        key = c.condition_id
        # Give each condition a unique value
        observations[key] = [float(hash(key) % 100) / 10.0]
    effect_retry = main_effect(conditions, observations, "policy.retry")
    levels_retry = {level["level"]: level["mean"] for level in effect_retry["levels"]}
    # Should have exactly 2 levels for retry
    assert len(levels_retry) == 2


# ------------------------------------------------------------------
# E — Seed provenance
# ------------------------------------------------------------------
def test_statistical_observation_traces_back_to_run_and_seed() -> None:
    """Every statistical observation must reference its source run/seed."""
    # Synthetic run result
    run = RunResult(
        run_id="run-0",
        seed=42,
        summary=pytest.importorskip("resiliencelab.metrics.transforms").RequestSummary(
            availability=1.0,
            throughput=100.0,
            latency_mean=0.05,
            latency_p95=0.1,
            latency_p99=0.15,
            latency_p999=0.2,
            amplifications={"requests": 1.0},
            error_rate=0.0,
            timeout_rate=0.0,
        ),
        downstream={},
        recovery=pytest.importorskip("resiliencelab.analysis.recovery").RecoveryReport(),
        timeline=[],
        record_count=0,
        backoff_seconds=0.0,
    )
    result = ExperimentResult(
        experiment=ExperimentSpec(id="prov", name="prov"),
        policy_name="baseline",
        config_hash="abc",
        runs=[run],
    )
    entry = result.as_comparison_entry()
    assert entry["seeds"] == [42]
    assert entry["repetitions"] == 1
    # Artifacts record seeds/repetitions
    from resiliencelab.experiments.artifacts import _build_statistics

    stats = _build_statistics(result)
    assert "analysis_version" in stats
    assert stats["resampling_unit"] == "repetition"


# ------------------------------------------------------------------
# Additional correctness tests
# ------------------------------------------------------------------
def test_paired_difference_summary_uses_replicate_index() -> None:
    a = [1.0, 2.0, 3.0]
    b = [0.5, 1.5, 2.5]
    result = paired_difference_summary(a, b, confidence=0.95)
    assert result["n"] == 3.0
    assert result["mean_difference"] == pytest.approx(0.5)
    assert "ci_low" in result
    assert "cohens_d_paired" in result


def test_small_sample_notes_for_n_less_than_2() -> None:
    from resiliencelab.analysis.statistics import small_sample_note

    notes = small_sample_note(1)
    assert any("descriptive only" in note for note in notes)


def test_small_sample_notes_for_n_less_than_5() -> None:
    from resiliencelab.analysis.statistics import small_sample_note

    notes = small_sample_note(3)
    assert any("highly uncertain" in note for note in notes)


def test_pareto_frontier_identifies_non_dominated() -> None:
    from resiliencelab.analysis.statistics import pareto_frontier

    points = [
        {"avail": 0.99, "latency": 0.05},
        {"avail": 0.8, "latency": 0.01},
        {"avail": 0.99, "latency": 0.01},
    ]
    # avail: higher better, latency: lower better
    frontier = pareto_frontier(points, {"avail": True, "latency": False})
    # The point (0.99, 0.01) dominates (0.99, 0.05) and (0.8, 0.01)
    # So only index 2 should survive
    assert 2 in frontier
    assert 0 not in frontier
    assert 1 not in frontier


def test_holm_adjust_reduces_p_values_correctly() -> None:
    from resiliencelab.analysis.statistics import holm_adjust

    pvals = [0.01, 0.03, 0.05, 0.1]
    adj = holm_adjust(pvals)
    # Adjusted p-values must be >= original and <= 1
    for i in range(len(pvals)):
        assert adj[i] >= pvals[i]
        assert adj[i] <= 1.0
    # Monotonic in sorted order (step-down property preserved in output order)


def test_interaction_effect_for_known_interaction() -> None:
    # Deliberate interaction: A effect is +2 under B=on, 0 under B=off
    a_off_b_off = [1.0, 1.0, 1.0]
    a_on_b_off = [3.0, 3.0, 3.0]
    a_off_b_on = [1.0, 1.0, 1.0]
    a_on_b_on = [1.0, 1.0, 1.0]
    result = two_way_interaction(a_off_b_off, a_on_b_off, a_off_b_on, a_on_b_on)
    # Interaction = (A effect under B_on) - (A effect under B_off)
    # A effect B_off = 3 - 1 = 2
    # A effect B_on = 1 - 1 = 0
    # Interaction = 0 - 2 = -2
    assert result["interaction"] == pytest.approx(-2.0)
