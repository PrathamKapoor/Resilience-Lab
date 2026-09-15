"""Automated factorial experiment-matrix generation (design-expansion layer)."""

from __future__ import annotations

from typing import Any

from resiliencelab.analysis.design import build_design
from resiliencelab.core.schema import ExperimentSpec


def generate_matrix(
    base: ExperimentSpec,
    factors: dict[str, list[Any]],
    *,
    id_template: str | None = None,
    name_template: str | None = None,
) -> list[ExperimentSpec]:
    conditions = build_design(base, factors)
    generated: list[ExperimentSpec] = []
    for condition in conditions:
        data = condition.spec.model_dump(mode="json")
        data["id"] = (
            f"{base.id}_{condition.condition_id}"
            if id_template is None
            else id_template.format(id=base.id, i=condition.index, combo_id=condition.condition_id)
        )
        data["name"] = (
            f"{base.name} [{condition.label()}]"
            if name_template is None
            else name_template.format(
                name=base.name, i=condition.index, combo_id=condition.condition_id
            )
        )
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
