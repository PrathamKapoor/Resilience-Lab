"""Per-service resilience policy resolution.

A ``PolicyResolver`` turns a single default policy plus optional per-service
overrides into a complete, concrete ``PolicySpec`` per service target. Policy
*configuration* is kept distinct from policy *runtime state*: each resolved
spec is later built into an independent executor via ``build_policy`` in
``core/builders.py``.
"""

from __future__ import annotations

from typing import Any

from resiliencelab.core.schema import ExperimentSpec, PolicySpec, merge_policy_dicts


def service_names(spec: ExperimentSpec) -> list[str]:
    if spec.system.services:
        return list(spec.system.call_order())
    return ["payment_service"]


class PolicyResolver:
    def __init__(
        self,
        default: PolicySpec,
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.default = default
        self.overrides = dict(overrides or {})

    def resolve(self, service_name: str) -> PolicySpec:
        override = self.overrides.get(service_name)
        if not override:
            return self.default
        merged = merge_policy_dicts(self.default.model_dump(), override)
        return PolicySpec.model_validate(merged)

    def resolved(self, service_names: list[str]) -> dict[str, PolicySpec]:
        return {name: self.resolve(name) for name in service_names}

    def effective(self, service_names: list[str]) -> dict[str, dict[str, Any]]:
        return {name: self.resolve(name).model_dump(mode="json") for name in service_names}
