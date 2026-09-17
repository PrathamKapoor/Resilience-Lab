"""C1 regression: factorial conditions must never share an artifact directory."""

from __future__ import annotations

import json
from pathlib import Path

from resiliencelab.analysis.design import build_design
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.artifacts import verify_artifacts, write_artifacts
from resiliencelab.experiments.factorial import CORE_FACTORS
from resiliencelab.experiments.matrix import (
    binary_factor_pairs,
    condition_dir,
    condition_metadata,
    condition_spec_for,
)
from resiliencelab.experiments.provenance import hash_config
from resiliencelab.experiments.result import ExperimentResult, RunResult
from resiliencelab.experiments.runner import ExperimentRunner


def _tiny_spec() -> ExperimentSpec:
    return ExperimentSpec.model_validate(
        {
            "id": "matrix_test",
            "name": "matrix test",
            "workload": {"type": "closed_loop", "clients": 2, "duration": "0.3s"},
            "repetitions": {"count": 1, "base_seed": 11},
        }
    )


def test_condition_dirs_are_distinct_and_deterministic(tmp_path: Path) -> None:
    spec = _tiny_spec()
    conditions = build_design(spec, CORE_FACTORS)
    assert len(conditions) == 64
    dirs = {condition_dir(tmp_path, spec.id, c.condition_id) for c in conditions}
    assert len(dirs) == 64
    # Deterministic: same base + same factors -> same condition ids/dirs
    again = build_design(spec, CORE_FACTORS)
    assert [c.condition_id for c in conditions] == [c.condition_id for c in again]
    for cond in conditions:
        assert (
            str(condition_dir(tmp_path, spec.id, cond.condition_id))
            .replace("\\", "/")
            .endswith(f"{spec.id}/conditions/{cond.condition_id}")
        )


def test_64_synthetic_conditions_do_not_overwrite(tmp_path: Path) -> None:
    spec = _tiny_spec()
    conditions = build_design(spec, CORE_FACTORS)
    for cond in conditions:
        cspec = condition_spec_for(spec, cond)
        assert cspec.id == f"{spec.id}_{cond.condition_id}"
        result = ExperimentResult(
            experiment=cspec,
            policy_name="baseline",
            config_hash=hash_config(cspec),
            runs=[],
        )
        dest = condition_dir(tmp_path, spec.id, cond.condition_id)
        manifest = write_artifacts(result, dest)
        (dest / "condition.json").write_text(
            json.dumps(condition_metadata(spec, cond, cspec.id)), encoding="utf-8"
        )
        assert manifest["experiment_id"] == cspec.id
    condition_roots = list((tmp_path / spec.id / "conditions").iterdir())
    assert len(condition_roots) == 64
    for cond in conditions:
        dest = condition_dir(tmp_path, spec.id, cond.condition_id)
        assert (dest / "manifest.json").exists()
        assert (dest / "condition.json").exists()
        assert (dest / "configuration.yaml").exists()
        verification = verify_artifacts(dest)
        assert verification["valid"] is True


def test_live_2x2_matrix_conditions_have_independent_manifests(tmp_path: Path) -> None:
    spec = _tiny_spec()
    factors = {
        "policy.retry": [None, {"enabled": True, "max_attempts": 2}],
        "policy.circuit_breaker": [None, {"enabled": True}],
    }
    conditions = build_design(spec, factors)
    assert len(conditions) == 4
    runner = ExperimentRunner()
    for cond in conditions:
        cspec = condition_spec_for(spec, cond)
        result = runner.run(cspec)
        dest = condition_dir(tmp_path, spec.id, cond.condition_id)
        write_artifacts(result, dest)
        (dest / "condition.json").write_text(
            json.dumps(condition_metadata(spec, cond, cspec.id)), encoding="utf-8"
        )
    for cond in conditions:
        verification = verify_artifacts(condition_dir(tmp_path, spec.id, cond.condition_id))
        assert verification["valid"] is True
        assert verification["verified_files"] == verification["file_count"]
    # Comparison entries must reference persisted artifact dirs
    entries = []
    for cond in conditions:
        dest = condition_dir(tmp_path, spec.id, cond.condition_id)
        manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
        entries.append(
            {
                "condition_id": cond.condition_id,
                "artifact_dir": f"conditions/{cond.condition_id}",
                "manifest_experiment": manifest["experiment_id"],
            }
        )
    assert len({e["artifact_dir"] for e in entries}) == 4


def test_rerun_one_condition_does_not_mutate_another(tmp_path: Path) -> None:
    from resiliencelab.analysis.recovery import RecoveryReport
    from resiliencelab.metrics.transforms import RequestSummary

    spec = _tiny_spec()
    factors = {"policy.retry": [None, {"enabled": True, "max_attempts": 2}]}
    conditions = build_design(spec, factors)
    assert len(conditions) == 2
    summary = RequestSummary(total=10, successful=9, failed=1, availability=0.9)
    for cond in conditions:
        cspec = condition_spec_for(spec, cond)
        result = ExperimentResult(
            experiment=cspec,
            policy_name="baseline",
            config_hash=hash_config(cspec),
            runs=[
                RunResult(
                    run_id=f"{cspec.id}/run-0",
                    seed=1,
                    summary=summary,
                    downstream={},
                    recovery=RecoveryReport(),
                    timeline=[],
                    record_count=1,
                    backoff_seconds=0.0,
                    records=[],
                    events=[],
                )
            ],
        )
        write_artifacts(result, condition_dir(tmp_path, spec.id, cond.condition_id))
    other = condition_dir(tmp_path, spec.id, conditions[1].condition_id)
    before = verify_artifacts(other)
    assert before["valid"] is True
    before_hashes = dict(json.loads((other / "manifest.json").read_text(encoding="utf-8"))["files"])
    # Rerun first condition with different content
    cspec0 = condition_spec_for(spec, conditions[0])
    rerun = ExperimentResult(
        experiment=cspec0,
        policy_name="rerun",
        config_hash=hash_config(cspec0),
        runs=[],
    )
    write_artifacts(rerun, condition_dir(tmp_path, spec.id, conditions[0].condition_id))
    after_hashes = dict(json.loads((other / "manifest.json").read_text(encoding="utf-8"))["files"])
    assert before_hashes == after_hashes
    assert verify_artifacts(other)["valid"] is True


def test_binary_factor_pairs_handles_dict_levels() -> None:
    spec = _tiny_spec()
    conditions = build_design(
        spec,
        {
            "policy.retry": [None, {"enabled": True, "max_attempts": 2}],
            "policy.circuit_breaker": [None, {"enabled": True}],
        },
    )
    pairs = binary_factor_pairs(["policy.retry", "policy.circuit_breaker"], conditions)
    assert pairs == [("policy.retry", "policy.circuit_breaker")]


def test_cancelled_condition_remains_independently_represented(tmp_path: Path) -> None:
    spec = _tiny_spec()
    factors = {"policy.retry": [None, {"enabled": True, "max_attempts": 2}]}
    conditions = build_design(spec, factors)
    complete_spec = condition_spec_for(spec, conditions[0])
    cancelled_spec = condition_spec_for(spec, conditions[1])
    complete = ExperimentResult(
        experiment=complete_spec,
        policy_name="baseline",
        config_hash=hash_config(complete_spec),
        runs=[],
    )
    cancelled = ExperimentResult(
        experiment=cancelled_spec,
        policy_name="baseline",
        config_hash=hash_config(cancelled_spec),
        runs=[],
        cancelled=True,
        cancellation_reason="test stop",
    )
    write_artifacts(complete, condition_dir(tmp_path, spec.id, conditions[0].condition_id))
    write_artifacts(cancelled, condition_dir(tmp_path, spec.id, conditions[1].condition_id))
    ok_dir = condition_dir(tmp_path, spec.id, conditions[0].condition_id)
    cancelled_dir = condition_dir(tmp_path, spec.id, conditions[1].condition_id)
    assert verify_artifacts(ok_dir)["valid"] is True
    assert verify_artifacts(cancelled_dir)["valid"] is True
    cancelled_manifest = json.loads((cancelled_dir / "manifest.json").read_text(encoding="utf-8"))
    assert cancelled_manifest["cancelled"] is True
    assert cancelled_manifest["cancellation_reason"] == "test stop"
    ok_manifest = json.loads((ok_dir / "manifest.json").read_text(encoding="utf-8"))
    assert ok_manifest["cancelled"] is False
