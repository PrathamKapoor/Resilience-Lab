"""Factorial experimental design: stable conditions, main effects, interactions.

The design layer gives identity and replication semantics to factorial
experiments. The **experimental unit** is a seeded repetition (a run); a
``DesignCondition`` is one factor combination, and its observations are the
per-run metrics of its repetitions.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Any

from resiliencelab.core.schema import ExperimentSpec


def _set_path(mapping: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    target = mapping
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = {}
            target[part] = child
        target = child
    if value is None:
        target.pop(parts[-1], None)
    else:
        target[parts[-1]] = value


def condition_hash(base_id: str, factors: dict[str, Any]) -> str:
    """Stable content hash identifying a factor combination."""
    payload = json.dumps({"base": base_id, "factors": factors}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def apply_factors(base: ExperimentSpec, factors: dict[str, Any]) -> ExperimentSpec:
    data = copy.deepcopy(base.model_dump(mode="json"))
    for path, value in factors.items():
        _set_path(data, path, value)
    return ExperimentSpec.model_validate(data)


@dataclass(frozen=True)
class DesignCondition:
    condition_id: str
    index: int
    factors: dict[str, Any]
    spec: ExperimentSpec

    def label(self) -> str:
        parts = []
        for key, value in self.factors.items():
            if value is None:
                rendered = "None"
            elif isinstance(value, dict):
                rendered = json.dumps(value, sort_keys=True, default=str)
            else:
                rendered = str(value)
            parts.append(f"{key}={rendered}")
        return ", ".join(parts)


def _canonical_level(level: Any) -> str:
    """Canonical key for a factor level, consistent with condition hashing."""
    return json.dumps(level, sort_keys=True, default=str)


def build_design(base: ExperimentSpec, factors: dict[str, list[Any]]) -> list[DesignCondition]:
    """Deterministic full-factorial expansion.

    Every condition keeps the base ``repetitions`` configuration, so the ith
    replicate of every condition shares the same seed (paired by replicate
    index). Condition IDs are content-hashed, not index-based.

    Duplicate factor levels are rejected: levels that are canonically equal
    (including ``None`` duplicates, duplicate primitives, and dict levels that
    differ only by key ordering) would generate semantically identical
    conditions and silently break ``condition_count`` accounting, so they raise
    ``ValueError``. Duplicate resulting conditions across nested factor paths
    are likewise rejected via condition-ID collision detection.
    """
    for path, levels in factors.items():
        seen: dict[str, int] = {}
        for pos, level in enumerate(levels):
            key = _canonical_level(level)
            if key in seen:
                raise ValueError(
                    f"duplicate factor level for {path!r}: "
                    f"positions {seen[key]} and {pos} are canonically equal "
                    f"({_canonical_level(level)}); remove or distinguish duplicates"
                )
            seen[key] = pos
    keys = list(factors.keys())
    value_sets = [factors[key] for key in keys]
    conditions: list[DesignCondition] = []
    seen_ids: dict[str, int] = {}
    for index, combo in enumerate(itertools.product(*value_sets)):
        assignments = dict(zip(keys, combo, strict=True))
        spec = apply_factors(base, assignments)
        cid = condition_hash(base.id, assignments)
        if cid in seen_ids:
            raise ValueError(
                f"duplicate factorial condition: index {index} collides with index "
                f"{seen_ids[cid]} (condition_id={cid}); factor levels across nested "
                "paths must produce distinct conditions"
            )
        seen_ids[cid] = index
        conditions.append(
            DesignCondition(
                condition_id=cid,
                index=index,
                factors=assignments,
                spec=spec,
            )
        )
    return conditions


def group_by_factor(
    conditions: list[DesignCondition],
    observations: dict[str, list[float]],
    factor: str,
) -> dict[Any, list[float]]:
    grouped_items: list[tuple[Any, list[float]]] = []
    for condition in conditions:
        level = condition.factors.get(factor)
        found = False
        for _i, (existing_level, vals) in enumerate(grouped_items):
            if existing_level == level:
                vals.extend(observations.get(condition.condition_id, []))
                found = True
                break
        if not found:
            grouped_items.append((level, list(observations.get(condition.condition_id, []))))
    result: dict[str, list[float]] = {}
    for level, vals in grouped_items:
        if isinstance(level, dict):
            key = json.dumps(level, sort_keys=True, default=str)
        else:
            key = "None" if level is None else str(level)
        result[key] = vals
    return result


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _finite_only(values: list[float]) -> tuple[list[float], int, int]:
    """Split values into finite (recovered) subset; returns (finite, n, n_recovered)."""
    import math

    finite: list[float] = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            finite.append(f)
    return finite, len(values), len(finite)


def _censored_cell_mean(values: list[float]) -> tuple[float | None, int, int, float]:
    """Recovered-only mean for a cell; None when no recovered observations."""
    finite, n, n_rec = _finite_only(values)
    rate = (n_rec / n) if n else 0.0
    if not finite:
        return None, n, n_rec, rate
    return sum(finite) / len(finite), n, n_rec, rate


def main_effect(
    conditions: list[DesignCondition],
    observations: dict[str, list[float]],
    factor: str,
) -> dict[str, Any]:
    """Per-level summary + effect size for one factor.

    ``effect`` is ``mean(level) - grand_mean`` for each level; for two levels
    the pairwise difference equals the spread between level effects.

    Censored values (``inf``/``nan``, i.e. unrecovered recovery runs) never
    enter arithmetic means: per-level means are recovered-only means. Cells
    with no recovered observations report ``mean=None``/``effect=None`` with
    an explicit note rather than a fabricated number.
    """
    grouped = group_by_factor(conditions, observations, factor)
    levels: list[dict[str, Any]] = []
    any_censored = False
    for level, vals in grouped.items():
        mean_val, n, n_rec, rate = _censored_cell_mean(vals)
        if n_rec < n:
            any_censored = True
        entry: dict[str, Any] = {
            "level": level,
            "n": n,
            "n_recovered": n_rec,
            "recovery_rate": rate,
            "mean": mean_val,
        }
        if mean_val is None:
            if n == 0:
                entry["note"] = "no observations"
            else:
                entry["note"] = f"no recovered observations (all {n} censored/unrecovered)"
        elif n_rec < n:
            entry["note"] = f"{n - n_rec}/{n} censored (inf excluded from mean)"
        levels.append(entry)
    defined = [lv["mean"] for lv in levels if lv.get("mean") is not None]
    grand: float | None = (sum(defined) / len(defined)) if defined else None
    for lv in levels:
        if lv.get("mean") is not None and grand is not None:
            lv["effect"] = float(lv["mean"]) - float(grand)
        else:
            lv["effect"] = None
            if "note" in lv:
                lv["note"] = str(lv["note"]) + "; effect undefined (censored)"
            else:
                lv["note"] = "effect undefined (censored cell with no recovered observations)"
    result: dict[str, Any] = {"factor": factor, "levels": levels, "grand_mean": grand}
    if any_censored:
        result["censored"] = True
        result["note"] = (
            "censored values (inf) excluded from means; effects are conditional on "
            "recovery (recovered-only means); cells with no recovered runs have mean/effect=null"
        )
    return result


def interaction_effect(
    conditions: list[DesignCondition],
    observations: dict[str, list[float]],
    factor_a: str,
    factor_b: str,
) -> dict[str, Any]:
    """Two-way difference-of-differences interaction for two factors.

    Censored values (``inf``/``nan``) never enter arithmetic means: cell means
    are recovered-only means. When any cell has no recovered observations the
    interaction is reported as ``None`` with an explicit note rather than a
    fabricated number.
    """
    a_levels_list: list[Any] = []
    for c in conditions:
        val = c.factors.get(factor_a)
        if val not in a_levels_list:
            a_levels_list.append(val)
    b_levels_list: list[Any] = []
    for c in conditions:
        val = c.factors.get(factor_b)
        if val not in b_levels_list:
            b_levels_list.append(val)
    if len(a_levels_list) != 2 or len(b_levels_list) != 2:
        raise ValueError("interaction_effect requires two binary factors")

    def cell(a: Any, b: Any) -> list[float]:
        for condition in conditions:
            if condition.factors.get(factor_a) == a and condition.factors.get(factor_b) == b:
                return observations.get(condition.condition_id, [])
        return []

    lo_a, hi_a = sorted(a_levels_list, key=str)
    lo_b, hi_b = sorted(b_levels_list, key=str)
    m00, n00, r00, _ = _censored_cell_mean(cell(lo_a, lo_b))
    m10, n10, r10, _ = _censored_cell_mean(cell(hi_a, lo_b))
    m01, n01, r01, _ = _censored_cell_mean(cell(lo_a, hi_b))
    m11, n11, r11, _ = _censored_cell_mean(cell(hi_a, hi_b))
    cells: dict[str, Any] = {
        f"cell_{factor_a}={lo_a}_{factor_b}={lo_b}": {"mean": m00, "n": n00, "n_recovered": r00},
        f"cell_{factor_a}={hi_a}_{factor_b}={lo_b}": {"mean": m10, "n": n10, "n_recovered": r10},
        f"cell_{factor_a}={lo_a}_{factor_b}={hi_b}": {"mean": m01, "n": n01, "n_recovered": r01},
        f"cell_{factor_a}={hi_a}_{factor_b}={hi_b}": {"mean": m11, "n": n11, "n_recovered": r11},
    }
    base: dict[str, Any] = {
        "factor_a": factor_a,
        "factor_b": factor_b,
        "cells": cells,
    }
    if m00 is None or m10 is None or m01 is None or m11 is None:
        base[f"effect_{factor_a}_given_{factor_b}={lo_b}"] = None
        base[f"effect_{factor_a}_given_{factor_b}={hi_b}"] = None
        base["interaction"] = None
        base["censored"] = True
        base["note"] = (
            "interaction undefined: at least one cell has no recovered observations "
            "(all censored/unrecovered); no number fabricated; see cells for per-cell counts"
        )
        return base
    effect_at_b0 = float(m10) - float(m00)
    effect_at_b1 = float(m11) - float(m01)
    interaction = effect_at_b1 - effect_at_b0
    base[f"effect_{factor_a}_given_{factor_b}={lo_b}"] = effect_at_b0
    base[f"effect_{factor_a}_given_{factor_b}={hi_b}"] = effect_at_b1
    base["interaction"] = interaction
    if r00 < n00 or r10 < n10 or r01 < n01 or r11 < n11:
        base["censored"] = True
        base["note"] = (
            "censored values (inf) excluded; effects are conditional on recovery "
            "(recovered-only cell means)"
        )
    return base
