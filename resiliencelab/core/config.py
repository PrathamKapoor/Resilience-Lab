"""Configuration loading and validation for experiments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from resiliencelab.core.schema import ExperimentSpec


class ConfigValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def parse_experiment(data: dict[str, Any]) -> ExperimentSpec:
    if not isinstance(data, dict):
        raise ConfigValidationError("configuration root must be a mapping")
    try:
        identity = data.get("experiment")
        if isinstance(identity, dict):
            merged = {key: value for key, value in data.items() if key != "experiment"}
            merged.update(identity)
            return ExperimentSpec.model_validate(merged)
        return ExperimentSpec.model_validate(data)
    except ValidationError as exc:
        raise ConfigValidationError(str(exc)) from exc


def load_yaml(path: str | Path) -> ExperimentSpec:
    """Load an experiment spec, normalizing YAML syntax errors.

    Raw ``yaml.YAMLError`` parser failures are wrapped into the public
    :class:`ConfigValidationError` at this configuration boundary so CLI and
    library callers observe one error contract and never a raw parser traceback.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigValidationError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigValidationError("configuration root must be a mapping")
    return parse_experiment(data)


def validate_data(data: dict[str, Any]) -> ExperimentSpec:
    try:
        return parse_experiment(data)
    except ValidationError as exc:
        raise ConfigValidationError(str(exc)) from exc


_IDENTITY_FIELDS = ("id", "name", "version", "description")


def to_dict(spec: ExperimentSpec) -> dict[str, Any]:
    data = spec.model_dump(mode="json")
    identity = {key: data.pop(key) for key in _IDENTITY_FIELDS if key in data}
    return {"experiment": identity, **data}


def dump_yaml(spec: ExperimentSpec) -> str:
    return yaml.safe_dump(to_dict(spec), sort_keys=False, default_flow_style=False)
