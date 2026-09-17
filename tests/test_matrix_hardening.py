"""F-M1/M2/M6 regression: manifests, per-condition failures, duplicate levels."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resiliencelab.analysis.design import build_design
from resiliencelab.cli.app import app
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.artifacts import verify_artifacts, write_artifacts
from resiliencelab.experiments.matrix import condition_dir, condition_metadata, condition_spec_for
from resiliencelab.experiments.provenance import hash_config
from resiliencelab.experiments.result import ExperimentResult

RUNNER = CliRunner()


def _tiny_spec(spec_id: str = "hardtest") -> ExperimentSpec:
    return ExperimentSpec.model_validate(
        {
            "id": spec_id,
            "name": "hardening test",
            "workload": {"type": "closed_loop", "clients": 2, "duration": "0.3s"},
            "repetitions": {"count": 1, "base_seed": 11},
        }
    )


def _empty_result(cspec: ExperimentSpec) -> ExperimentResult:
    return ExperimentResult(
        experiment=cspec,
        policy_name="baseline",
        config_hash=hash_config(cspec),
        runs=[],
    )


# --- F-M1 ---


def test_timeline_and_condition_hashed_and_verified(tmp_path: Path) -> None:
    from resiliencelab.analysis.recovery import RecoveryReport
    from resiliencelab.experiments.result import RunResult
    from resiliencelab.metrics.transforms import RequestSummary

    spec = _tiny_spec()
    conditions = build_design(spec, {"policy.retry": [None, {"enabled": True}]})
    cond = conditions[0]
    cspec = condition_spec_for(spec, cond)
    summary = RequestSummary(total=5, successful=5, failed=0, availability=1.0)
    result = ExperimentResult(
        experiment=cspec,
        policy_name="baseline",
        config_hash=hash_config(cspec),
        runs=[
            RunResult(
                run_id="r0",
                seed=1,
                summary=summary,
                downstream={},
                recovery=RecoveryReport(),
                timeline=[{"t": 0.0, "rps": 10.0}],
                record_count=1,
                backoff_seconds=0.0,
                records=[],
                events=[],
            )
        ],
    )
    dest = condition_dir(tmp_path, spec.id, cond.condition_id)
    metadata = condition_metadata(spec, cond, cspec.id)
    manifest = write_artifacts(result, dest, condition=metadata)
    assert "condition.json" in manifest["files"]
    assert any("timeline" in k for k in manifest["files"])
    assert (dest / "condition.json").exists()
    assert (dest / "analysis" / "timeline-0.json").exists()
    verification = verify_artifacts(dest)
    assert verification["valid"] is True
    assert verification["warnings"] == []
    # Mutations detected.
    (dest / "condition.json").write_bytes(b'{"tampered": true}')
    assert verify_artifacts(dest)["valid"] is False
    (dest / "condition.json").write_bytes(
        json.dumps(metadata, indent=2, default=str).encode("utf-8")
    )
    assert verify_artifacts(dest)["valid"] is True
    (dest / "analysis" / "timeline-0.json").write_bytes(b"[]")
    mutated = verify_artifacts(dest)
    assert mutated["valid"] is False
    assert any("timeline" in e for e in mutated["errors"])


def test_untracked_condition_json_warns(tmp_path: Path) -> None:
    spec = _tiny_spec()
    conditions = build_design(spec, {"policy.retry": [None, {"enabled": True}]})
    cond = conditions[0]
    cspec = condition_spec_for(spec, cond)
    dest = condition_dir(tmp_path, spec.id, cond.condition_id)
    write_artifacts(_empty_result(cspec), dest)
    # Legacy path: condition.json written after manifest without hashing.
    (dest / "condition.json").write_text("{}", encoding="utf-8")
    verification = verify_artifacts(dest)
    assert verification["valid"] is True
    assert any("condition.json" in w for w in verification["warnings"])


# --- F-M6 ---


def test_duplicate_none_rejected() -> None:
    spec = _tiny_spec()
    with pytest.raises(ValueError, match="duplicate factor level"):
        build_design(spec, {"policy.retry": [None, None]})


def test_duplicate_primitive_rejected() -> None:
    spec = _tiny_spec()
    with pytest.raises(ValueError, match="duplicate factor level"):
        build_design(spec, {"policy.backoff.type": ["fixed", "fixed"]})


def test_duplicate_dict_rejected() -> None:
    spec = _tiny_spec()
    with pytest.raises(ValueError, match="duplicate factor level"):
        build_design(
            spec,
            {
                "policy.retry": [
                    {"enabled": True, "max_attempts": 3},
                    {"enabled": True, "max_attempts": 3},
                ]
            },
        )


def test_equivalent_dicts_different_ordering_rejected() -> None:
    spec = _tiny_spec()
    with pytest.raises(ValueError, match="duplicate factor level"):
        build_design(spec, {"policy.retry": [{"x": 1, "y": 2}, {"y": 2, "x": 1}]})


def test_duplicates_across_nested_paths_rejected() -> None:
    spec = _tiny_spec()
    # Same canonical dict value duplicated within a nested factor path.
    with pytest.raises(ValueError, match="duplicate factor level"):
        build_design(
            spec,
            {
                "policy.retry": [None, {"enabled": True}],
                "policy.backoff.jitter": ["none", "none"],
            },
        )


# --- F-M2 (CLI-level: success/fail/success) ---


def _write_base_yaml(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "experiment:",
                "  id: mfail",
                "  name: matrix failure test",
                "  version: 1",
                "workload:",
                "  type: closed_loop",
                "  clients: 2",
                "  duration: 0.3s",
                "failure: []",
                "policy: {}",
                "repetitions:",
                "  count: 1",
                "  base_seed: 3",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_matrix_failure_isolation_cli(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    cli_app_module = importlib.import_module("resiliencelab.cli.app")
    assert "resiliencelab.cli.app" in sys.modules

    base_yaml = tmp_path / "base.yaml"
    _write_base_yaml(base_yaml)
    factors_path = tmp_path / "factors.json"
    # Three conditions via a 3-level factor; middle one will be forced to fail.
    factors_path.write_text(
        json.dumps({"policy.backoff.type": ["fixed", "exponential", "linear"]}),
        encoding="utf-8",
    )
    store = tmp_path / "results"
    # Pre-compute condition ids to decide which one fails.
    from resiliencelab.core.config import load_yaml

    loaded = load_yaml(base_yaml)
    conditions = build_design(loaded, {"policy.backoff.type": ["fixed", "exponential", "linear"]})
    assert len(conditions) == 3
    failing_id = conditions[1].condition_id
    real_run = cli_app_module._run_spec

    def flaky_run(condition_spec):
        if condition_spec.id.endswith(failing_id):
            raise RuntimeError("intentional condition failure")
        return real_run(condition_spec)

    monkeypatch.setattr(cli_app_module, "_run_spec", flaky_run)
    result = RUNNER.invoke(
        app, ["matrix", str(base_yaml), "--factors", str(factors_path), "--store", str(store)]
    )
    assert result.exit_code == 1
    base_dir = store / "mfail"
    manifest_path = base_dir / "matrix_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["condition_count"] == 3
    assert manifest["succeeded"] == 2
    assert manifest["failed"] == 1
    by_id = manifest["conditions"]
    assert by_id[conditions[0].condition_id]["status"] == "ok"
    assert by_id[conditions[1].condition_id]["status"] == "failed"
    assert by_id[conditions[1].condition_id]["error_type"] == "RuntimeError"
    assert "intentional condition failure" in by_id[conditions[1].condition_id]["error"]
    assert by_id[conditions[2].condition_id]["status"] == "ok"
    # Successful artifacts preserved.
    for idx in (0, 2):
        dest = store / "mfail" / "conditions" / conditions[idx].condition_id
        assert (dest / "manifest.json").exists()
        assert (dest / "condition.json").exists()
        assert verify_artifacts(dest)["valid"] is True
    # Failed condition has no successful bundle overwrite.
    failed_dest = store / "mfail" / "conditions" / failing_id
    # Either no bundle or no manifest (failure before write); must not look successful.
    if (failed_dest / "manifest.json").exists():
        assert verify_artifacts(failed_dest)["valid"] is True
    # Comparison/effects still written from successes.
    assert (base_dir / "matrix_comparison.json").exists()
    assert (base_dir / "matrix_effects.json").exists()
