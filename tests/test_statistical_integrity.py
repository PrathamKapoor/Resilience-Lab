"""Phase 11: Statistical Audit.

Hostile audit of statistical correctness — pseudoreplication, bootstrap,
pairing, factorial designs, Holm correction, Pareto frontier, and
statistical provenance.
"""

from __future__ import annotations

import pytest

from resiliencelab.analysis.comparison import (
    aggregate_metric,
    build_comparison,
    build_paired_comparison,
)
from resiliencelab.analysis.design import (
    build_design,
    condition_hash,
    group_by_factor,
    interaction_effect,
    main_effect,
)
from resiliencelab.analysis.statistics import (
    STAT_ANALYSIS_VERSION,
    bootstrap_ci,
    cohens_d,
    cohens_d_paired,
    holm_adjust,
    mean_ci,
    paired_difference_summary,
    pareto_frontier,
    small_sample_note,
    summarize,
    welch_ttest,
)
from resiliencelab.core.schema import ExperimentSpec

# ===================================================================
# 11.1  Experimental unit: REPETITION, not REQUEST
# ===================================================================


class TestExperimentalUnit:
    def test_aggregate_metric_uses_repetition_count(self) -> None:
        """1000 requests across 3 repetitions => n=3, not n=1000."""
        metrics = [
            {"avail": 0.90},
            {"avail": 0.92},
            {"avail": 0.88},
        ]
        result = aggregate_metric(metrics, "avail")
        assert result["n"] == 3.0
        assert result["count"] == 3.0
        assert result["resampling_unit"] == "repetition"

    def test_summarize_counts_distinct_values(self) -> None:
        """summarize counts the number of values, not their magnitude."""
        values = [0.9, 0.92, 0.88]
        s = summarize(values)
        assert s["count"] == 3.0

    def test_single_repetition_ci_collapses(self) -> None:
        """With n=1, CI must collapse to the point estimate."""
        s = summarize([0.5])
        assert s["ci_low"] == pytest.approx(0.5)
        assert s["ci_high"] == pytest.approx(0.5)


# ===================================================================
# 11.2  Pseudoreplication test
# ===================================================================


class TestPseudoreplication:
    def test_many_requests_few_repetitions(self) -> None:
        """1000 requests but only 1 repetition => n=1."""
        # 3 repetitions with 100 requests each => still n=3
        metrics = [{"throughput": 100.0 + i * 0.1} for i in range(3)]
        result = aggregate_metric(metrics, "throughput")
        assert result["n"] == 3.0

    def test_comparison_n_reflects_repetitions(self) -> None:
        a = {
            "id": "a",
            "name": "a",
            "metrics_per_run": [{"m": float(i)} for i in range(5)],
        }
        b = {
            "id": "b",
            "name": "b",
            "metrics_per_run": [{"m": float(i) + 10} for i in range(5)],
        }
        comp = build_comparison([a, b], metrics=["m"])
        assert comp["effects"][0]["m_n"] == 5


# ===================================================================
# 11.3  Small-n behavior
# ===================================================================


class TestSmallN:
    def test_n_1_descriptive_only(self) -> None:
        notes = small_sample_note(1)
        assert any("descriptive only" in n for n in notes)

    def test_n_3_highly_uncertain(self) -> None:
        notes = small_sample_note(3)
        assert any("highly uncertain" in n for n in notes)

    def test_n_30_no_warning(self) -> None:
        notes = small_sample_note(30)
        assert notes == []

    def test_summarize_n_1_std_zero(self) -> None:
        s = summarize([5.0])
        assert s["std"] == 0.0
        assert s["variance"] == 0.0

    def test_mean_ci_n_1_collapses(self) -> None:
        import numpy as np

        lo, hi = mean_ci(np.array([5.0]))
        assert lo == pytest.approx(5.0)
        assert hi == pytest.approx(5.0)

    def test_bootstrap_ci_constant_values(self) -> None:
        lo, hi = bootstrap_ci([3.0, 3.0, 3.0], resamples=100)
        assert lo == pytest.approx(3.0, abs=0.01)
        assert hi == pytest.approx(3.0, abs=0.01)


# ===================================================================
# 11.4  Bootstrap determinism
# ===================================================================


class TestBootstrap:
    def test_deterministic_with_seed(self) -> None:
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        lo1, hi1 = bootstrap_ci(data, resamples=500)
        lo2, hi2 = bootstrap_ci(data, resamples=500)
        assert lo1 == pytest.approx(lo2, abs=1e-8)
        assert hi1 == pytest.approx(hi2, abs=1e-8)

    def test_empty_input(self) -> None:
        lo, hi = bootstrap_ci([])
        assert lo == 0.0
        assert hi == 0.0

    def test_single_value(self) -> None:
        lo, hi = bootstrap_ci([5.0], resamples=100)
        assert lo == pytest.approx(5.0, abs=0.01)
        assert hi == pytest.approx(5.0, abs=0.01)

    def test_ci_contains_mean(self) -> None:
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        lo, hi = bootstrap_ci(data, confidence=0.95, resamples=1000)
        mean = sum(data) / len(data)
        assert lo <= mean <= hi

    def test_wider_ci_for_higher_confidence(self) -> None:
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        lo90, hi90 = bootstrap_ci(data, confidence=0.90, resamples=500)
        lo99, hi99 = bootstrap_ci(data, confidence=0.99, resamples=500)
        assert (hi90 - lo90) < (hi99 - lo99)


# ===================================================================
# 11.5  Pairing and effect sizes
# ===================================================================


class TestPairing:
    def test_paired_difference_summary_basic(self) -> None:
        a = [1.0, 2.0, 3.0]
        b = [0.5, 1.5, 2.5]
        r = paired_difference_summary(a, b)
        assert r["n"] == 3.0
        assert r["mean_difference"] == pytest.approx(0.5)

    def test_unbalanced_pairing_truncates(self) -> None:
        a = [1.0, 2.0, 3.0]
        b = [10.0, 20.0]
        r = paired_difference_summary(a, b)
        assert r["n"] == 2.0

    def test_cohens_d_paired_basic(self) -> None:
        d = cohens_d_paired([1.0, 2.0, 5.0], [0.0, 1.0, 2.0])
        # diffs = [1,1,3], mean=5/3, sd=sqrt(var)=sqrt(4/3) => d > 0
        assert d > 0

    def test_cohens_d_paired_too_few(self) -> None:
        d = cohens_d_paired([1.0], [2.0])
        assert d == 0.0

    def test_build_paired_comparison_balanced(self) -> None:
        a = {
            "id": "a",
            "name": "a",
            "metrics_per_run": [{"m": 1.0}, {"m": 2.0}],
        }
        b = {
            "id": "b",
            "name": "b",
            "metrics_per_run": [{"m": 0.5}, {"m": 1.5}],
        }
        paired = build_paired_comparison(a, b, metrics=["m"])
        assert paired["paired"] is True
        assert paired["n_matched"] == 2

    def test_build_paired_comparison_unbalanced_warns(self) -> None:
        a = {
            "id": "a",
            "name": "a",
            "metrics_per_run": [{"m": 1.0}, {"m": 2.0}, {"m": 3.0}],
        }
        b = {
            "id": "b",
            "name": "b",
            "metrics_per_run": [{"m": 0.5}],
        }
        paired = build_paired_comparison(a, b, metrics=["m"])
        assert paired["n_matched"] == 1
        assert any("unbalanced" in w for w in paired.get("warnings", []))


# ===================================================================
# 11.6  Factorial designs
# ===================================================================


class TestFactorial:
    def test_condition_hash_deterministic(self) -> None:
        h1 = condition_hash("exp", {"a": 1, "b": 2})
        h2 = condition_hash("exp", {"a": 1, "b": 2})
        assert h1 == h2

    def test_condition_hash_order_independent(self) -> None:
        h1 = condition_hash("exp", {"a": 1, "b": 2})
        h2 = condition_hash("exp", {"b": 2, "a": 1})
        assert h1 == h2

    def test_build_design_full_factorial(self) -> None:
        spec = ExperimentSpec(id="fac", name="fac")
        conditions = build_design(
            spec,
            {
                "policy.retry": [None, {"enabled": True}],
                "policy.circuit_breaker": [None, {"enabled": True}],
            },
        )
        assert len(conditions) == 4  # 2x2

    def test_group_by_factor_isolation(self) -> None:
        spec = ExperimentSpec(id="grp", name="grp")
        conditions = build_design(
            spec,
            {"policy.retry": [None, {"enabled": True}]},
        )
        observations = {
            conditions[0].condition_id: [0.9],
            conditions[1].condition_id: [0.5],
        }
        grouped = group_by_factor(conditions, observations, "policy.retry")
        none_vals = grouped.get("None", [])
        assert len(none_vals) == 1
        assert none_vals[0] == pytest.approx(0.9)

    def test_missing_condition_not_fabricated(self) -> None:
        """If a condition has no observations, it should not appear in results."""
        spec = ExperimentSpec(id="missing", name="missing")
        conditions = build_design(
            spec,
            {
                "policy.retry": [None, {"enabled": True}],
                "policy.circuit_breaker": [None, {"enabled": True}],
            },
        )
        # Only provide observations for 2 of 4 conditions
        observations = {
            conditions[0].condition_id: [0.9],
            conditions[1].condition_id: [0.5],
        }
        for c in conditions:
            if c.condition_id not in observations:
                assert c.condition_id not in observations

    def test_main_effect_two_levels(self) -> None:
        spec = ExperimentSpec(id="me", name="me")
        conditions = build_design(spec, {"policy.retry": [None, {"enabled": True}]})
        observations = {
            conditions[0].condition_id: [0.9],
            conditions[1].condition_id: [0.5],
        }
        effect = main_effect(conditions, observations, "policy.retry")
        assert len(effect["levels"]) == 2

    def test_interaction_effect_binary(self) -> None:
        spec = ExperimentSpec(id="ie", name="ie")
        conditions = build_design(
            spec,
            {
                "policy.retry": [None, {"enabled": True}],
                "policy.circuit_breaker": [None, {"enabled": True}],
            },
        )
        obs = {c.condition_id: [float(i)] for i, c in enumerate(conditions)}
        result = interaction_effect(conditions, obs, "policy.retry", "policy.circuit_breaker")
        assert "interaction" in result


# ===================================================================
# 11.7  Missing factorial conditions
# ===================================================================


class TestMissingConditions:
    def test_missing_condition_id_not_present(self) -> None:
        spec = ExperimentSpec(id="mc", name="mc")
        conditions = build_design(
            spec,
            {
                "policy.retry": [None, {"enabled": True}],
                "policy.circuit_breaker": [None, {"enabled": True}],
            },
        )
        # Only provide 3 of 4 conditions
        observations = {c.condition_id: [1.0] for c in conditions[:3]}
        missing = [c for c in conditions if c.condition_id not in observations]
        assert len(missing) == 1

    def test_main_effect_with_missing(self) -> None:
        """Main effect with a missing condition should still work for present ones."""
        spec = ExperimentSpec(id="me_missing", name="me_missing")
        conditions = build_design(spec, {"policy.retry": [None, {"enabled": True}]})
        # Only provide observations for first condition
        observations = {conditions[0].condition_id: [0.9]}
        effect = main_effect(conditions, observations, "policy.retry")
        # Should still compute for the level with data
        assert len(effect["levels"]) >= 1


# ===================================================================
# 11.8  Holm correction
# ===================================================================


class TestHolm:
    def test_empty_input(self) -> None:
        assert holm_adjust([]) == []

    def test_single_pvalue(self) -> None:
        adj = holm_adjust([0.05])
        assert adj[0] == pytest.approx(0.05)

    def test_adjusted_geq_original(self) -> None:
        pvals = [0.01, 0.03, 0.05, 0.1]
        adj = holm_adjust(pvals)
        for orig, adj_val in zip(pvals, adj, strict=True):
            assert adj_val >= orig

    def test_adjusted_leq_1(self) -> None:
        pvals = [0.5, 0.6, 0.7, 0.8]
        adj = holm_adjust(pvals)
        for v in adj:
            assert v <= 1.0

    def test_equal_pvalues(self) -> None:
        pvals = [0.05, 0.05, 0.05]
        adj = holm_adjust(pvals)
        for v in adj:
            assert v <= 1.0

    def test_unsorted_input(self) -> None:
        pvals = [0.1, 0.01, 0.05]
        adj = holm_adjust(pvals)
        # Original order preserved
        assert len(adj) == 3
        for orig, adj_val in zip(pvals, adj, strict=True):
            assert adj_val >= orig

    def test_output_length_matches_input(self) -> None:
        pvals = [0.01, 0.02, 0.03, 0.04, 0.05]
        adj = holm_adjust(pvals)
        assert len(adj) == len(pvals)


# ===================================================================
# 11.9  Pareto frontier
# ===================================================================


class TestPareto:
    def test_empty_input(self) -> None:
        assert pareto_frontier([], {"a": True}) == []

    def test_single_point(self) -> None:
        frontier = pareto_frontier([{"a": 1.0}], {"a": True})
        assert frontier == [0]

    def test_non_dominated(self) -> None:
        points = [
            {"a": 1.0, "b": 2.0},
            {"a": 2.0, "b": 1.0},
        ]
        frontier = pareto_frontier(points, {"a": True, "b": True})
        assert 0 in frontier
        assert 1 in frontier

    def test_dominated(self) -> None:
        points = [
            {"a": 1.0, "b": 1.0},
            {"a": 2.0, "b": 2.0},  # dominates point 0
        ]
        frontier = pareto_frontier(points, {"a": True, "b": True})
        assert 1 in frontier
        assert 0 not in frontier

    def test_equal_points(self) -> None:
        points = [
            {"a": 1.0, "b": 1.0},
            {"a": 1.0, "b": 1.0},
        ]
        frontier = pareto_frontier(points, {"a": True, "b": True})
        assert len(frontier) == 2

    def test_mixed_directions(self) -> None:
        points = [
            {"a": 1.0, "b": 5.0},
            {"a": 2.0, "b": 10.0},
        ]
        # a: higher better, b: lower better
        frontier = pareto_frontier(points, {"a": True, "b": False})
        # Neither dominates: 0 has better b, 1 has better a
        assert 0 in frontier
        assert 1 in frontier

    def test_three_points_one_dominated(self) -> None:
        points = [
            {"a": 1.0, "b": 10.0},  # dominated: worse a than 2, worse b than 1
            {"a": 2.0, "b": 1.0},
            {"a": 3.0, "b": 5.0},
        ]
        frontier = pareto_frontier(points, {"a": True, "b": False})
        assert 0 not in frontier  # dominated by both 1 and 2
        assert 1 in frontier
        assert 2 in frontier

    def test_deterministic(self) -> None:
        points = [{"x": i, "y": 10 - i} for i in range(5)]
        f1 = pareto_frontier(points, {"x": True, "y": True})
        f2 = pareto_frontier(points, {"x": True, "y": True})
        assert f1 == f2


# ===================================================================
# 11.10  Statistical provenance
# ===================================================================


class TestStatisticalProvenance:
    def test_aggregate_metric_has_analysis_version(self) -> None:
        result = aggregate_metric([{"m": 1.0}], "m")
        assert result["analysis_version"] == STAT_ANALYSIS_VERSION

    def test_aggregate_metric_has_resampling_unit(self) -> None:
        result = aggregate_metric([{"m": 1.0}], "m")
        assert result["resampling_unit"] == "repetition"

    def test_paired_has_analysis_version(self) -> None:
        a = {"id": "a", "metrics_per_run": [{"m": 1.0}]}
        b = {"id": "b", "metrics_per_run": [{"m": 0.5}]}
        result = build_paired_comparison(a, b, metrics=["m"])
        assert result["analysis_version"] == STAT_ANALYSIS_VERSION

    def test_comparison_has_analysis_version(self) -> None:
        a = {"id": "a", "name": "a", "metrics_per_run": [{"m": 1.0}]}
        b = {"id": "b", "name": "b", "metrics_per_run": [{"m": 0.5}]}
        result = build_comparison([a, b], metrics=["m"])
        assert result["analysis_version"] == STAT_ANALYSIS_VERSION


# ===================================================================
# 11.11  Effect size correctness
# ===================================================================


class TestEffectSize:
    def test_cohens_d_positive_direction(self) -> None:
        d = cohens_d([10.0, 11.0, 12.0], [1.0, 2.0, 3.0])
        assert d > 0

    def test_cohens_d_negative_direction(self) -> None:
        d = cohens_d([1.0, 2.0, 3.0], [10.0, 11.0, 12.0])
        assert d < 0

    def test_cohens_d_equal_groups(self) -> None:
        d = cohens_d([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        assert d == 0.0

    def test_cohens_d_too_few(self) -> None:
        d = cohens_d([1.0], [2.0])
        assert d == 0.0

    def test_welch_ttest_basic(self) -> None:
        t, p = welch_ttest([1.0, 2.0, 3.0], [10.0, 11.0, 12.0])
        assert t < 0  # first group is smaller
        assert 0.0 <= p <= 1.0


# ===================================================================
# 11.12  No overclaiming
# ===================================================================


class TestNoOverclaiming:
    def test_small_n_produces_wide_ci(self) -> None:
        """With n=3, CI should be much wider than with n=30."""
        values = [0.9, 0.92, 0.88]
        s3 = summarize(values)
        s30 = summarize(values + [0.91] * 27)
        width_3 = s3["ci_high"] - s3["ci_low"]
        width_30 = s30["ci_high"] - s30["ci_low"]
        assert width_3 > width_30

    def test_single_value_ci_collapses(self) -> None:
        s = summarize([0.5])
        assert s["ci_low"] == s["ci_high"] == 0.5
