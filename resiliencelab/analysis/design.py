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


def build_design(base: ExperimentSpec, factors: dict[str, list[Any]]) -> list[DesignCondition]:
    """Deterministic full-factorial expansion.

    Every condition keeps the base ``repetitions`` configuration, so the ith
    replicate of every condition shares the same seed (paired by replicate
    index). Condition IDs are content-hashed, not index-based.
    """
    keys = list(factors.keys())
    value_sets = [factors[key] for key in keys]
    conditions: list[DesignCondition] = []
    for index, combo in enumerate(itertools.product(*value_sets)):
        assignments = dict(zip(keys, combo, strict=True))
        spec = apply_factors(base, assignments)
        conditions.append(
            DesignCondition(
                condition_id=condition_hash(base.id, assignments),
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


def main_effect(
    conditions: list[DesignCondition],
    observations: dict[str, list[float]],
    factor: str,
) -> dict[str, Any]:
    """Per-level summary + effect size for one factor.

    ``effect`` is ``mean(level) - grand_mean`` for each level; for two levels
    the pairwise difference equals the spread between level effects.
    """
    grouped = group_by_factor(conditions, observations, factor)
    levels = [
        {"level": level, "n": len(vals), "mean": _mean(vals)} for level, vals in grouped.items()
    ]
    grand = _mean([level["mean"] for level in levels])
    for level in levels:
        level["effect"] = level["mean"] - grand
    return {"factor": factor, "levels": levels, "grand_mean": grand}


def interaction_effect(
    conditions: list[DesignCondition],
    observations: dict[str, list[float]],
    factor_a: str,
    factor_b: str,
) -> dict[str, Any]:
    """Two-way difference-of-differences interaction for two factors."""
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
    a0b0 = _mean(cell(lo_a, lo_b))
    a1b0 = _mean(cell(hi_a, lo_b))
    a0b1 = _mean(cell(lo_a, hi_b))
    a1b1 = _mean(cell(hi_a, hi_b))
    effect_at_b0 = a1b0 - a0b0
    effect_at_b1 = a1b1 - a0b1
    interaction = effect_at_b1 - effect_at_b0
    return {
        "factor_a": factor_a,
        "factor_b": factor_b,
        f"effect_{factor_a}_given_{factor_b}={lo_b}": effect_at_b0,
        f"effect_{factor_a}_given_{factor_b}={hi_b}": effect_at_b1,
        "interaction": interaction,
    }
