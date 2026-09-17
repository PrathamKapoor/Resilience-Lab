"""Deterministic factorial-matrix artifact layout.
Two distinct factorial conditions MUST NEVER write to the same artifact
directory. Layout::

    <store>/<base_experiment_id>/
      matrix_design.json
      matrix_comparison.json
      matrix_effects.json
      matrix_manifest.json
      conditions/<condition_id>/
        configuration.yaml
        experiment.json
        condition.json
        environment.json
        raw/...
        analysis/...
        report/...
        manifest.json

``condition_id`` is the deterministic content hash from
``analysis.design.condition_hash``. The per-condition experiment id is
``f"{base_id}_{condition_id}"`` so stored bundles are unique even if copied.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resiliencelab.analysis.design import DesignCondition
from resiliencelab.core.schema import ExperimentSpec


def condition_dir(store: Path | str, base_experiment_id: str, condition_id: str) -> Path:
    return Path(store) / base_experiment_id / "conditions" / condition_id


def condition_spec_for(base_spec: ExperimentSpec, condition: DesignCondition) -> ExperimentSpec:
    data = condition.spec.model_dump(mode="json")
    data["id"] = f"{base_spec.id}_{condition.condition_id}"
    data["name"] = f"{base_spec.name} [{condition.label()}]"
    return ExperimentSpec.model_validate(data)


def condition_metadata(
    base_spec: ExperimentSpec, condition: DesignCondition, spec_id: str
) -> dict[str, Any]:
    return {
        "base_experiment_id": base_spec.id,
        "base_experiment_name": base_spec.name,
        "condition_id": condition.condition_id,
        "condition_index": condition.index,
        "condition_hash": condition.condition_id,
        "factors": condition.factors,
        "label": condition.label(),
        "spec_id": spec_id,
        "artifact_dir": f"conditions/{condition.condition_id}",
    }


def binary_factor_pairs(
    factor_names: list[str], conditions: list[DesignCondition]
) -> list[tuple[str, str]]:
    """Factor pairs with exactly two levels each (dict-safe canonicalization)."""
    pairs: list[tuple[str, str]] = []
    for i, fa in enumerate(factor_names):
        for fb in factor_names[i + 1 :]:
            a_levels = {
                json.dumps(c.factors.get(fa), sort_keys=True, default=str) for c in conditions
            }
            b_levels = {
                json.dumps(c.factors.get(fb), sort_keys=True, default=str) for c in conditions
            }
            if len(a_levels) == 2 and len(b_levels) == 2:
                pairs.append((fa, fb))
    return pairs
