"""In-memory experiment/result registry with optional filesystem persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resiliencelab.core.config import dump_yaml, load_yaml
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.result import ExperimentResult


class ExperimentRegistry:
    def __init__(self, store_dir: Path | None = None) -> None:
        self._specs: dict[str, ExperimentSpec] = {}
        self._results: dict[str, ExperimentResult] = {}
        self._store_dir = Path(store_dir) if store_dir else None
        if self._store_dir:
            self._load_specs()

    def register_spec(self, spec: ExperimentSpec) -> None:
        self._specs[spec.id] = spec
        self._save_spec(spec)

    def register_result(self, result: ExperimentResult) -> None:
        self._results[result.experiment_id] = result

    def get_spec(self, experiment_id: str) -> ExperimentSpec | None:
        return self._specs.get(experiment_id)

    def get_result(self, experiment_id: str) -> ExperimentResult | None:
        return self._results.get(experiment_id)

    def spec_ids(self) -> list[str]:
        return sorted(self._specs)

    def result_ids(self) -> list[str]:
        return sorted(self._results)

    def _spec_path(self, experiment_id: str) -> Path:
        assert self._store_dir is not None
        return self._store_dir / "specs" / f"{experiment_id}.yaml"

    def _save_spec(self, spec: ExperimentSpec) -> None:
        if self._store_dir is None:
            return
        path = self._spec_path(spec.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_yaml(spec), encoding="utf-8")

    def _load_specs(self) -> None:
        assert self._store_dir is not None
        specs_dir = self._store_dir / "specs"
        if not specs_dir.exists():
            return
        for path in sorted(specs_dir.glob("*.yaml")):
            try:
                spec = load_yaml(path)
                self._specs[spec.id] = spec
            except Exception:  # noqa: BLE001
                continue

    def export_index(self) -> dict[str, Any]:
        return {
            "specs": {spec_id: dump_yaml(spec) for spec_id, spec in self._specs.items()},
            "results": list(self._results.keys()),
        }

    def write_index(self) -> None:
        if self._store_dir is None:
            return
        self._store_dir.mkdir(parents=True, exist_ok=True)
        (self._store_dir / "index.json").write_text(
            json.dumps(self.export_index(), indent=2), encoding="utf-8"
        )
