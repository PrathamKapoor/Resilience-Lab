"""F-C5b regression: recovery gate provenance must be persisted and consistent."""

from __future__ import annotations

import json
from pathlib import Path

from resiliencelab.analysis.recovery import RecoveryReport
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.artifacts import (
    _build_statistics,
    verify_artifacts,
    write_artifacts,
)
from resiliencelab.experiments.provenance import hash_config
from resiliencelab.experiments.result import ExperimentResult, RunResult
from resiliencelab.metrics.transforms import RequestSummary


def _summary() -> RequestSummary:
    return RequestSummary(
        total=10,
        successful=9,
        failed=1,
        availability=0.9,
        throughput=50.0,
        latency_mean=0.01,
        latency_p95=0.02,
        latency_p99=0.03,
        amplifications={"requests": 1.0},
    )


def _make_result() -> ExperimentResult:
    spec = ExperimentSpec(id="provtest", name="provtest")
    runs = [
        RunResult(
            run_id="provtest/run-0",
            seed=11,
            summary=_summary(),
            downstream={},
            recovery=RecoveryReport(
                baseline_throughput=100.0,
                baseline_p95_latency=0.05,
                degraded=True,
                degraded_at=5.0,
                recovered_at=9.0,
                time_to_recovery=4.0,
                gates_evaluated=["throughput", "latency"],
                latency_gate=0.0625,
                latency_degraded=True,
                latency_recovered=True,
            ),
            timeline=[],
            record_count=1,
            backoff_seconds=0.0,
            records=[],
            events=[],
        ),
        RunResult(
            run_id="provtest/run-1",
            seed=12,
            summary=_summary(),
            downstream={},
            recovery=RecoveryReport(
                baseline_throughput=100.0,
                baseline_p95_latency=0.05,
                degraded=True,
                degraded_at=5.0,
                recovered_at=None,
                time_to_recovery=float("inf"),
                gates_evaluated=["throughput", "latency"],
                latency_gate=0.0625,
                latency_degraded=True,
                latency_recovered=False,
            ),
            timeline=[],
            record_count=1,
            backoff_seconds=0.0,
            records=[],
            events=[],
        ),
    ]
    return ExperimentResult(
        experiment=spec,
        policy_name="baseline",
        config_hash=hash_config(spec),
        runs=runs,
    )


def test_experiment_json_persists_gate_fields(tmp_path: Path) -> None:
    result = _make_result()
    base = tmp_path / "bundle"
    write_artifacts(result, base)
    exp = json.loads((base / "experiment.json").read_text(encoding="utf-8"))
    assert "recovery" in exp
    rec = exp["recovery"]
    assert "thresholds" in rec
    assert "stability_window" in rec
    assert "per_run" in rec
    assert len(rec["per_run"]) == 2
    for entry, run in zip(rec["per_run"], result.runs, strict=True):
        assert entry["gates_evaluated"] == run.recovery.gates_evaluated
        assert entry["latency_gate"] == run.recovery.latency_gate
        assert entry["baseline_p95_latency"] == run.recovery.baseline_p95_latency
        assert entry["latency_recovered"] == run.recovery.latency_recovered
    # Thresholds must match the spec analysis config.
    assert (
        rec["thresholds"]["availability_threshold"]
        == result.experiment.analysis.availability_threshold
    )
    assert rec["thresholds"]["stability_window"] == float(
        result.experiment.analysis.stability_window
    )


def test_statistics_json_consistent_with_experiment_json(tmp_path: Path) -> None:
    result = _make_result()
    base = tmp_path / "bundle"
    write_artifacts(result, base)
    exp = json.loads((base / "experiment.json").read_text(encoding="utf-8"))
    stats = json.loads((base / "analysis" / "statistics.json").read_text(encoding="utf-8"))
    assert "recovery" in stats
    assert stats["recovery"]["thresholds"] == exp["recovery"]["thresholds"]
    assert stats["recovery"]["per_run"] == exp["recovery"]["per_run"]
    # Direct helper path is identical.
    direct = _build_statistics(result)
    assert direct["recovery"] == stats["recovery"]


def test_report_contains_gate_decision_line(tmp_path: Path) -> None:
    result = _make_result()
    base = tmp_path / "bundle"
    write_artifacts(result, base)
    md = (base / "report" / "report.md").read_text(encoding="utf-8")
    assert "Recovery gates:" in md
    assert "throughput=" in md
    assert "latency=" in md
    # Report line must match the in-memory gate line (no invented values).
    assert result.recovery_gate_line() in md
    # Bundle must still verify.
    assert verify_artifacts(base)["valid"] is True


def test_live_runner_provenance_matches_artifact(tmp_path: Path) -> None:
    from resiliencelab.experiments.runner import ExperimentRunner

    spec = ExperimentSpec.model_validate(
        {
            "id": "liveprov",
            "name": "liveprov",
            "workload": {"type": "closed_loop", "clients": 2, "duration": "0.3s"},
            "repetitions": {"count": 1, "base_seed": 7},
        }
    )
    result = ExperimentRunner().run(spec)
    base = tmp_path / "live"
    write_artifacts(result, base)
    exp = json.loads((base / "experiment.json").read_text(encoding="utf-8"))
    assert "recovery" in exp
    assert len(exp["recovery"]["per_run"]) == len(result.runs)
    for entry, run in zip(exp["recovery"]["per_run"], result.runs, strict=True):
        assert entry["gates_evaluated"] == run.recovery.gates_evaluated
        assert entry["latency_gate"] == run.recovery.latency_gate
        assert entry["baseline_p95_latency"] == run.recovery.baseline_p95_latency
        assert entry["latency_recovered"] == run.recovery.latency_recovered
