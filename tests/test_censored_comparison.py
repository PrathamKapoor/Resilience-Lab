"""F-C6b regression: censored recovery must not poison comparisons/matrix/paired."""

from __future__ import annotations

import json
import math

from resiliencelab.analysis.comparison import (
    aggregate_metric,
    build_comparison,
    build_paired_comparison,
)
from resiliencelab.analysis.design import build_design, interaction_effect, main_effect
from resiliencelab.analysis.interactions import two_way_interaction
from resiliencelab.analysis.statistics import summarize_censored
from resiliencelab.core.schema import ExperimentSpec


def _is_poisoned(value: object) -> bool:
    if isinstance(value, float):
        return value != value or value == float("inf") or value == float("-inf")
    return False


def _scan_no_poisoned(obj: object, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        # Poisoned pattern is specifically mean=inf, std=nan, CI=[nan,nan]
        # but any inf/nan in aggregated summaries is a failure except raw
        # per-run observations (metrics_per_run) which legitimately hold inf.
        if "metrics_per_run" in obj:
            # Do not scan raw per-run lists; scan the rest.
            for k, v in obj.items():
                if k == "metrics_per_run":
                    continue
                found.extend(_scan_no_poisoned(v, f"{path}.{k}"))
            return found
        for k, v in obj.items():
            # Raw observation lists keyed by condition are checked separately;
            # aggregated mean/std/ci keys must never be non-finite.
            if k in (
                "mean",
                "std",
                "variance",
                "ci_low",
                "ci_high",
                "mean_difference",
                "median_difference",
                "interaction",
            ) and _is_poisoned(v):
                found.append(f"{path}.{k}={v!r}")
            else:
                found.extend(_scan_no_poisoned(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(_scan_no_poisoned(v, f"{path}[{i}]"))
    elif _is_poisoned(obj):
        # Top-level floats outside metrics_per_run are poisoned, except explicit
        # None handling: floats that are inf/nan anywhere aggregated are bad.
        # Raw per-run inf is excluded by the caller.
        found.append(f"{path}={obj!r}")
    return found


def test_aggregate_mixed_does_not_return_inf_nan() -> None:
    runs = [{"recovery_time": v} for v in [float("inf"), 5.0, 6.0]]
    out = aggregate_metric(runs, "recovery_time")
    assert out.get("mean") != float("inf")
    assert not _is_poisoned(out.get("mean", 0.0))
    for key in ("ci_low", "ci_high", "std"):
        if key in out and out[key] is not None:
            assert not _is_poisoned(out[key]), f"{key}={out[key]!r}"
    assert out["recovery_rate"] == 2.0 / 3.0


def test_aggregate_all_censored_has_no_inf_mean() -> None:
    runs = [{"recovery_time": float("inf")} for _ in range(3)]
    out = aggregate_metric(runs, "recovery_time")
    assert "mean" not in out or out["mean"] is None
    assert not any(_is_poisoned(v) for v in out.values() if isinstance(v, float))
    assert out["recovery_rate"] == 0.0


def test_aggregate_all_recovered_ordinary() -> None:
    runs = [{"recovery_time": v} for v in [5.0, 6.0, 7.0]]
    out = aggregate_metric(runs, "recovery_time")
    assert math.isfinite(float(out["mean"]))
    assert math.isfinite(float(out["ci_low"]))
    assert math.isfinite(float(out["ci_high"]))


def test_aggregate_two_value_edges() -> None:
    for vals in ([float("inf"), 5.0], [5.0, float("inf")]):
        runs = [{"recovery_time": v} for v in vals]
        out = aggregate_metric(runs, "recovery_time")
        assert not any(
            _is_poisoned(v)
            for k, v in out.items()
            if k in ("mean", "std", "ci_low", "ci_high") and isinstance(v, float)
        )


def test_summarize_censored_all_censored_no_inf() -> None:
    stats = summarize_censored([float("inf")] * 3)
    assert "mean" not in stats or stats["mean"] is None
    assert not any(_is_poisoned(v) for v in stats.values() if isinstance(v, float))


def test_comparison_output_has_no_poisoned_recovery() -> None:
    a = {
        "id": "a",
        "name": "a",
        "metrics_per_run": [
            {"recovery_time": float("inf")},
            {"recovery_time": 5.0},
            {"recovery_time": 6.0},
        ],
    }
    b = {
        "id": "b",
        "name": "b",
        "metrics_per_run": [
            {"recovery_time": 5.0},
            {"recovery_time": 6.0},
            {"recovery_time": 7.0},
        ],
    }
    comp = build_comparison([a, b], metrics=["recovery_time"])
    poisoned = _scan_no_poisoned(comp)
    assert poisoned == [], f"poisoned values: {poisoned}"
    # Effect for censored recovery must be explicit, not nan.
    effect = comp["effects"][0]
    assert effect["recovery_time_cohens_d"] is None
    assert "recovery_time_cohens_d_note" in effect
    # Serialized JSON must not contain Infinity/NaN literals.
    text = json.dumps(comp, allow_nan=False, default=str)
    assert "Infinity" not in text
    assert "NaN" not in text


def test_paired_recovery_does_not_propagate_inf() -> None:
    a = {
        "id": "a",
        "name": "a",
        "metrics_per_run": [
            {"recovery_time": float("inf")},
            {"recovery_time": 5.0},
        ],
    }
    b = {
        "id": "b",
        "name": "b",
        "metrics_per_run": [
            {"recovery_time": 5.0},
            {"recovery_time": 6.0},
        ],
    }
    paired = build_paired_comparison(a, b, metrics=["recovery_time"])
    stats = paired["metrics"]["recovery_time"]
    for key in ("mean_difference", "ci_low", "ci_high"):
        if key in stats and stats[key] is not None:
            assert not _is_poisoned(stats[key]), f"{key}={stats[key]!r}"
    text = json.dumps(paired, allow_nan=False, default=str)
    assert "Infinity" not in text


def test_paired_all_censored_explicit() -> None:
    a = {"id": "a", "metrics_per_run": [{"recovery_time": float("inf")}]}
    b = {"id": "b", "metrics_per_run": [{"recovery_time": float("inf")}]}
    paired = build_paired_comparison(a, b, metrics=["recovery_time"])
    stats = paired["metrics"]["recovery_time"]
    assert "mean_difference" not in stats or stats["mean_difference"] is None
    assert "note" in stats


def test_main_effect_single_censored_cell() -> None:
    spec = ExperimentSpec(id="c6b", name="c6b")
    conditions = build_design(
        spec,
        {
            "policy.retry": [None, {"enabled": True}],
            "policy.circuit_breaker": [None, {"enabled": True}],
        },
    )
    # Only one cell censored (all inf), others recovered.
    obs: dict[str, list[float]] = {}
    for i, c in enumerate(conditions):
        if i == 0:
            obs[c.condition_id] = [float("inf"), float("inf")]
        else:
            obs[c.condition_id] = [5.0, 6.0]
    for factor in ("policy.retry", "policy.circuit_breaker"):
        eff = main_effect(conditions, obs, factor)
        for level in eff["levels"]:
            if level["mean"] is not None:
                assert math.isfinite(float(level["mean"]))
            if level["effect"] is not None:
                assert math.isfinite(float(level["effect"]))
        assert eff["grand_mean"] is None or math.isfinite(float(eff["grand_mean"]))
        text = json.dumps(eff, allow_nan=False, default=str)
        assert "Infinity" not in text
    inter = interaction_effect(conditions, obs, "policy.retry", "policy.circuit_breaker")
    if inter["interaction"] is not None:
        assert math.isfinite(float(inter["interaction"]))
    text = json.dumps(inter, allow_nan=False, default=str)
    assert "Infinity" not in text


def test_two_way_interaction_censored_cell_explicit() -> None:
    res = two_way_interaction([float("inf"), float("inf")], [5.0, 6.0], [5.0, 6.0], [5.0, 6.0])
    assert res["interaction"] is None
    assert "note" in res
