"""Automated factorial experiment-matrix generation."""

from __future__ import annotations

import copy
import itertools
from typing import Any

from resiliencelab.core.schema import ExperimentSpec


def _set_path(mapping: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    target = mapping
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    if value is None:
        target.pop(parts[-1], None)
    else:
        target[parts[-1]] = value


def generate_matrix(
    base: ExperimentSpec,
    factors: dict[str, list[Any]],
    *,
    id_template: str = "{id}_{i:02d}",
    name_template: str = "{name} [{i}]",
) -> list[ExperimentSpec]:
    keys = list(factors.keys())
    if not keys:
        return [base]
    value_sets = [factors[key] for key in keys]
    base_data = base.model_dump(mode="json")
    generated: list[ExperimentSpec] = []
    for index, combo in enumerate(itertools.product(*value_sets)):
        data = copy.deepcopy(base_data)
        for path, value in zip(keys, combo, strict=True):
            _set_path(data, path, value)
        data["id"] = id_template.format(id=base.id, i=index)
        data["name"] = name_template.format(name=base.name, i=index)
        generated.append(ExperimentSpec.model_validate(data))
    return generated


CORE_FACTORS: dict[str, list[Any]] = {
    "policy.retry": [None, {"enabled": True, "max_attempts": 3}],
    "policy.backoff.type": ["fixed", "exponential"],
    "policy.backoff.jitter": ["none", "full"],
    "policy.circuit_breaker": [
        None,
        {"enabled": True, "threshold": 10, "recovery_window": "15s"},
    ],
    "policy.concurrency": [None, {"enabled": True, "limit": 50, "queue_limit": 0}],
    "policy.timeout.total": [None, "1s"],
}
