from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from resiliencelab.core.config import (
    ConfigValidationError,
    dump_yaml,
    load_yaml,
    parse_experiment,
    validate_data,
)


def _minimal() -> dict:
    return {"experiment": {"id": "exp_x", "name": "x"}}


def test_nested_convention() -> None:
    spec = parse_experiment({**_minimal(), "experiment": {**_minimal()["experiment"]}})
    assert spec.id == "exp_x"


def test_spec_style_convention() -> None:
    spec = parse_experiment(
        {
            "experiment": {"id": "exp_y", "name": "y"},
            "workload": {"type": "closed_loop", "clients": 4, "duration": "2s"},
            "repetitions": {"count": 3, "base_seed": 7},
        }
    )
    assert spec.id == "exp_y"
    assert spec.workload.clients == 4
    assert spec.repetitions.count == 3


def test_duration_strings() -> None:
    spec = parse_experiment(
        {
            "experiment": {"id": "exp_d", "name": "d"},
            "workload": {"duration": "100ms", "warmup": "10ms"},
            "policy": {"backoff": {"base": "100ms", "maximum": "5s"}},
        }
    )
    assert spec.workload.duration == pytest.approx(0.1)
    assert spec.policy.backoff.base == pytest.approx(0.1)
    assert spec.policy.backoff.maximum == pytest.approx(5.0)


def test_invalid_probability_rejected() -> None:
    with pytest.raises((ValidationError, ConfigValidationError)):
        validate_data(
            {
                "experiment": {"id": "bad", "name": "bad"},
                "failure": [{"probability": 1.5}],
            }
        )


def test_warmup_longer_than_duration_rejected() -> None:
    with pytest.raises((ValidationError, ConfigValidationError)):
        validate_data(
            {
                "experiment": {"id": "bad", "name": "bad"},
                "workload": {"duration": "1s", "warmup": "2s"},
            }
        )


def test_service_graph_accepted_and_ordered() -> None:
    spec = parse_experiment(
        {
            "experiment": {"id": "exp_g", "name": "g"},
            "system": {
                "services": [
                    {"name": "inventory_service", "depends_on": ["payment_service"]},
                    {"name": "payment_service"},
                ]
            },
            "failure": [{"target": "inventory_service"}],
        }
    )
    assert spec.system.call_order() == ["payment_service", "inventory_service"]


def test_unknown_failure_target_rejected() -> None:
    with pytest.raises((ValidationError, ConfigValidationError)):
        validate_data(
            {
                "experiment": {"id": "bad", "name": "bad"},
                "system": {"services": [{"name": "payment_service"}]},
                "failure": [{"target": "unknown_service"}],
            }
        )


def test_legacy_config_accepts_any_target() -> None:
    spec = parse_experiment(
        {
            "experiment": {"id": "exp_l", "name": "l"},
            "failure": [{"target": "whatever_service"}],
        }
    )
    assert spec.failure[0].target == "whatever_service"


def test_duplicate_service_names_rejected() -> None:
    with pytest.raises((ValidationError, ConfigValidationError)):
        validate_data(
            {
                "experiment": {"id": "bad", "name": "bad"},
                "system": {
                    "services": [{"name": "a"}, {"name": "a"}],
                },
            }
        )


def test_unknown_dependency_rejected() -> None:
    with pytest.raises((ValidationError, ConfigValidationError)):
        validate_data(
            {
                "experiment": {"id": "bad", "name": "bad"},
                "system": {"services": [{"name": "a", "depends_on": ["ghost"]}]},
            }
        )


def test_cyclic_services_rejected() -> None:
    with pytest.raises((ValidationError, ConfigValidationError)):
        validate_data(
            {
                "experiment": {"id": "bad", "name": "bad"},
                "system": {
                    "services": [
                        {"name": "a", "depends_on": ["b"]},
                        {"name": "b", "depends_on": ["a"]},
                    ],
                },
            }
        )


def test_round_trip_dump_and_reload(tmp_path) -> None:
    spec = parse_experiment(
        {
            "experiment": {"id": "exp_r", "name": "r"},
            "workload": {"clients": 3, "duration": "1s"},
        }
    )
    path = tmp_path / "exp.yaml"
    path.write_text(dump_yaml(spec), encoding="utf-8")
    reloaded = load_yaml(path)
    assert reloaded.id == spec.id
    assert reloaded.workload.clients == 3
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["experiment"]["id"] == "exp_r"
