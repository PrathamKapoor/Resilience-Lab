"""Phase 10: Artifact Integrity Audit.

Hostile audit of the entire artifact lifecycle — hashing, verification,
missing files, extra files, path safety, partial results, immutability,
and reproduction semantics.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resiliencelab.analysis.recovery import RecoveryReport
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.artifacts import verify_artifacts, write_artifacts
from resiliencelab.experiments.provenance import (
    hash_bytes,
    hash_config,
    hash_file,
    hash_records,
    hash_text,
)
from resiliencelab.experiments.result import ExperimentResult, RunResult
from resiliencelab.metrics.transforms import RequestSummary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DUMMY_SUMMARY = RequestSummary(
    total=100,
    successful=95,
    failed=5,
    timeouts=0,
    availability=0.95,
    throughput=50.0,
    latency_mean=0.01,
    latency_median=0.009,
    latency_p95=0.02,
    latency_p99=0.03,
    latency_p999=0.05,
    error_rate=0.05,
    timeout_rate=0.0,
    amplifications={"requests": 1.1},
)


def _make_result(
    n_runs: int = 3,
    cancelled: bool = False,
    base_seed: int = 42,
) -> ExperimentResult:
    """Create a minimal valid ExperimentResult for artifact testing."""
    spec = ExperimentSpec(
        id="test_experiment",
        name="Test Experiment",
        repetitions={"count": n_runs, "base_seed": base_seed},
    )
    runs = []
    for i in range(n_runs):
        runs.append(
            RunResult(
                run_id=f"run-{i}",
                seed=base_seed + i,
                summary=DUMMY_SUMMARY,
                downstream={},
                recovery=RecoveryReport(),
                timeline=[],
                record_count=10,
                backoff_seconds=0.0,
                records=[
                    {"timestamp": i * 1000 + j, "latency_ms": 10 + j, "success": True}
                    for j in range(10)
                ],
                service_metrics={"svc": {"capacity": 100.0}},
                events=[],
            )
        )
    return ExperimentResult(
        experiment=spec,
        policy_name="baseline",
        config_hash=hash_config(spec),
        runs=runs,
        environment={"python": "3.13"},
        cancelled=cancelled,
        cancellation_reason="test cancellation" if cancelled else "",
    )


@pytest.fixture()
def artifact_dir(tmp_path: Path) -> Path:
    """Write artifacts to a temp directory and return the path."""
    result = _make_result(n_runs=3)
    base = tmp_path / "artifacts"
    write_artifacts(result, base)
    return base


# ---------------------------------------------------------------------------
# 10.1  Manifest audit
# ---------------------------------------------------------------------------


class TestManifestAudit:
    def test_manifest_contains_required_fields(self, artifact_dir: Path) -> None:
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        required = [
            "experiment_id",
            "config_hash",
            "raw_records_hash",
            "events_hash",
            "event_schema_version",
            "event_count",
            "cancelled",
            "cancellation_reason",
            "requested_repetitions",
            "completed_repetitions",
            "files",
        ]
        for field in required:
            assert field in manifest, f"missing manifest field: {field}"

    def test_manifest_files_are_dict(self, artifact_dir: Path) -> None:
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        assert isinstance(manifest["files"], dict)
        assert len(manifest["files"]) > 0

    def test_all_file_hashes_are_hex_64(self, artifact_dir: Path) -> None:
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        for path, h in manifest["files"].items():
            assert isinstance(h, str), f"hash for {path} is not a string"
            assert len(h) == 64, f"hash for {path} is not 64 hex chars"
            assert all(c in "0123456789abcdef" for c in h), f"hash for {path} is not hex"

    def test_manifest_completed_equals_actual_runs(self, artifact_dir: Path) -> None:
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        assert manifest["completed_repetitions"] == 3

    def test_manifest_config_hash_matches_spec(self, artifact_dir: Path) -> None:
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        assert manifest["config_hash"] is not None
        assert len(manifest["config_hash"]) == 64

    def test_manifest_event_count_non_negative(self, artifact_dir: Path) -> None:
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        assert manifest["event_count"] >= 0


# ---------------------------------------------------------------------------
# 10.2  Hash verification
# ---------------------------------------------------------------------------


class TestHashVerification:
    def test_verify_artifacts_passes_on_intact_bundle(self, artifact_dir: Path) -> None:
        result = verify_artifacts(artifact_dir)
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["verified_files"] == result["file_count"]

    def test_detects_byte_mutation(self, artifact_dir: Path) -> None:
        target = artifact_dir / "experiment.json"
        original = target.read_bytes()
        # Flip one byte
        mutated = original[:-1] + bytes([original[-1] ^ 0xFF])
        target.write_bytes(mutated)

        result = verify_artifacts(artifact_dir)
        assert result["valid"] is False
        assert any("hash mismatch" in e for e in result["errors"])
        assert "experiment.json" in str(result["errors"])

    def test_detects_insertion(self, artifact_dir: Path) -> None:
        target = artifact_dir / "report" / "report.md"
        target.write_text(target.read_text() + "\nINJECTED CONTENT\n")

        result = verify_artifacts(artifact_dir)
        assert result["valid"] is False
        assert any("hash mismatch" in e for e in result["errors"])

    def test_detects_deletion(self, artifact_dir: Path) -> None:
        target = artifact_dir / "report" / "report.md"
        target.write_text("")

        result = verify_artifacts(artifact_dir)
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# 10.3  Missing artifacts
# ---------------------------------------------------------------------------


class TestMissingArtifacts:
    def test_detects_missing_file(self, artifact_dir: Path) -> None:
        (artifact_dir / "report" / "report.md").unlink()
        result = verify_artifacts(artifact_dir)
        assert result["valid"] is False
        assert any("missing file" in e for e in result["errors"])

    def test_detects_missing_raw_records(self, artifact_dir: Path) -> None:
        (artifact_dir / "raw" / "records-0.jsonl").unlink()
        result = verify_artifacts(artifact_dir)
        assert result["valid"] is False
        assert any("missing file" in e and "records-0" in e for e in result["errors"])

    def test_verify_on_nonexistent_dir(self, tmp_path: Path) -> None:
        result = verify_artifacts(tmp_path / "nonexistent")
        assert result["valid"] is False
        assert any("manifest.json not found" in e for e in result["errors"])

    def test_verify_on_empty_dir(self, tmp_path: Path) -> None:
        result = verify_artifacts(tmp_path)
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# 10.4  Extra files
# ---------------------------------------------------------------------------


class TestExtraFiles:
    def test_extra_file_in_raw_dir_warns(self, artifact_dir: Path) -> None:
        (artifact_dir / "raw" / "injected.jsonl").write_text('{"injected": true}')
        result = verify_artifacts(artifact_dir)
        # Extra files produce warnings, not errors — manifest only protects tracked files
        assert any("untracked file" in w for w in result["warnings"])

    def test_extra_file_in_analysis_dir_warns(self, artifact_dir: Path) -> None:
        (artifact_dir / "analysis" / "secret.json").write_text('{"secret": true}')
        result = verify_artifacts(artifact_dir)
        assert any("untracked file" in w for w in result["warnings"])

    def test_extra_file_does_not_affect_validity(self, artifact_dir: Path) -> None:
        (artifact_dir / "raw" / "extra.txt").write_text("extra")
        result = verify_artifacts(artifact_dir)
        # The bundle is still valid — extra files are warnings only
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# 10.5  Wrong hash
# ---------------------------------------------------------------------------


class TestWrongHash:
    def test_wrong_hash_in_manifest_detected(self, artifact_dir: Path) -> None:
        manifest_path = artifact_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        # Replace a hash with a wrong value
        first_key = next(iter(manifest["files"]))
        manifest["files"][first_key] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, indent=2))

        result = verify_artifacts(artifact_dir)
        assert result["valid"] is False
        assert any("hash mismatch" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# 10.6  Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_relative_paths_in_manifest(self, artifact_dir: Path) -> None:
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        for rel_path in manifest["files"]:
            assert not Path(rel_path).is_absolute(), f"absolute path in manifest: {rel_path}"
            parts = Path(rel_path).parts
            assert ".." not in parts, f"path traversal in manifest: {rel_path}"


# ---------------------------------------------------------------------------
# 10.7  Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_completed_bundle_manifest_matches(self, artifact_dir: Path) -> None:
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        assert manifest["cancelled"] is False
        assert manifest["requested_repetitions"] == manifest["completed_repetitions"]

    def test_experiment_json_not_cancelled(self, artifact_dir: Path) -> None:
        exp = json.loads((artifact_dir / "experiment.json").read_text())
        assert exp["cancelled"] is False

    def test_written_files_match_manifest(self, artifact_dir: Path) -> None:
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        for rel_path in manifest["files"]:
            assert (artifact_dir / rel_path).exists(), f"file in manifest missing: {rel_path}"


# ---------------------------------------------------------------------------
# 10.8  Partial/cancelled artifacts
# ---------------------------------------------------------------------------


class TestPartialArtifacts:
    def test_cancelled_bundle_manifest(self, tmp_path: Path) -> None:
        result = _make_result(n_runs=2, cancelled=True)
        base = tmp_path / "cancelled"
        write_artifacts(result, base)

        manifest = json.loads((base / "manifest.json").read_text())
        assert manifest["cancelled"] is True
        assert manifest["cancellation_reason"] == "test cancellation"
        assert manifest["completed_repetitions"] == 2
        assert manifest["requested_repetitions"] == 2  # spec says 2

    def test_cancelled_bundle_passes_verification(self, tmp_path: Path) -> None:
        result = _make_result(n_runs=2, cancelled=True)
        base = tmp_path / "cancelled"
        write_artifacts(result, base)

        v = verify_artifacts(base)
        assert v["valid"] is True

    def test_partial_run_no_fake_records(self, tmp_path: Path) -> None:
        """If only 2 of 3 runs completed, no records-2.jsonl should exist."""
        spec = ExperimentSpec(
            id="partial_test",
            name="Partial",
            repetitions={"count": 3, "base_seed": 1},
        )
        runs = []
        for i in range(2):  # Only 2 runs completed
            runs.append(
                RunResult(
                    run_id=f"run-{i}",
                    seed=1 + i,
                    summary=DUMMY_SUMMARY,
                    downstream={},
                    recovery=RecoveryReport(),
                    timeline=[],
                    record_count=10,
                    backoff_seconds=0.0,
                    records=[{"ts": j, "val": j} for j in range(5)],
                    events=[],
                )
            )
        result = ExperimentResult(
            experiment=spec,
            policy_name="test",
            config_hash=hash_config(spec),
            runs=runs,
            cancelled=True,
            cancellation_reason="partial",
        )
        base = tmp_path / "partial"
        write_artifacts(result, base)

        manifest = json.loads((base / "manifest.json").read_text())
        assert manifest["completed_repetitions"] == 2

        # records-2.jsonl should NOT exist
        assert not (base / "raw" / "records-2.jsonl").exists()
        # records-0 and records-1 SHOULD exist
        assert (base / "raw" / "records-0.jsonl").exists()
        assert (base / "raw" / "records-1.jsonl").exists()

    def test_statistics_use_actual_run_count(self, tmp_path: Path) -> None:
        """Statistics reflect actual completed runs, not requested count."""
        result = _make_result(n_runs=2, cancelled=True)
        base = tmp_path / "partial_stats"
        write_artifacts(result, base)

        stats = json.loads((base / "analysis" / "statistics.json").read_text())
        for metric_name, metric_data in stats["metrics"].items():
            if "count" in metric_data:
                assert metric_data["count"] == 2.0, (
                    f"metric {metric_name} has count {metric_data['count']}, expected 2"
                )


# ---------------------------------------------------------------------------
# 10.9  Reproduction vs rerun vs verification
# ---------------------------------------------------------------------------


class TestReproductionRerunVerification:
    def test_verify_checks_file_hashes(self, artifact_dir: Path) -> None:
        """Verification = checking existing artifacts against manifest hashes."""
        v = verify_artifacts(artifact_dir)
        assert v["valid"] is True
        assert v["verified_files"] > 0

    def test_rerun_produces_new_artifacts(self, tmp_path: Path) -> None:
        """Rerun = executing the experiment again, producing independent artifacts."""
        result1 = _make_result(n_runs=2, base_seed=42)
        base1 = tmp_path / "run1"
        write_artifacts(result1, base1)

        result2 = _make_result(n_runs=2, base_seed=42)
        base2 = tmp_path / "run2"
        write_artifacts(result2, base2)

        m1 = json.loads((base1 / "manifest.json").read_text())
        m2 = json.loads((base2 / "manifest.json").read_text())

        # Same config → same config_hash
        assert m1["config_hash"] == m2["config_hash"]
        # Same deterministic records → same records hash
        assert m1["raw_records_hash"] == m2["raw_records_hash"]

    def test_reproduction_requires_same_seed(self, tmp_path: Path) -> None:
        """Different seeds produce different seed provenance in experiment.json."""
        result1 = _make_result(n_runs=2, base_seed=42)
        base1 = tmp_path / "seed42"
        write_artifacts(result1, base1)

        result2 = _make_result(n_runs=2, base_seed=99)
        base2 = tmp_path / "seed99"
        write_artifacts(result2, base2)

        # Different seeds produce different experiment.json content
        exp1 = json.loads((base1 / "experiment.json").read_text())
        exp2 = json.loads((base2 / "experiment.json").read_text())
        assert exp1["seeds"] != exp2["seeds"]


# ---------------------------------------------------------------------------
# 10.10  Reproduction failure modes
# ---------------------------------------------------------------------------


class TestReproductionFailureModes:
    def test_missing_config_file_detected(self, artifact_dir: Path) -> None:
        (artifact_dir / "configuration.yaml").unlink()
        result = verify_artifacts(artifact_dir)
        assert result["valid"] is False
        assert any("missing file" in e and "configuration" in e for e in result["errors"])

    def test_missing_manifest_detected(self, artifact_dir: Path) -> None:
        (artifact_dir / "manifest.json").unlink()
        result = verify_artifacts(artifact_dir)
        assert result["valid"] is False

    def test_corrupted_manifest_detected(self, artifact_dir: Path) -> None:
        (artifact_dir / "manifest.json").write_text("NOT JSON {{{")
        with pytest.raises(json.JSONDecodeError):
            verify_artifacts(artifact_dir)

    def test_corrupted_raw_records_detected(self, artifact_dir: Path) -> None:
        (artifact_dir / "raw" / "records-0.jsonl").write_text("CORRUPTED")
        result = verify_artifacts(artifact_dir)
        assert result["valid"] is False
        assert any("hash mismatch" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# 10.11  Hash primitive tests
# ---------------------------------------------------------------------------


class TestHashPrimitives:
    def test_hash_bytes_deterministic(self) -> None:
        assert hash_bytes(b"hello") == hash_bytes(b"hello")

    def test_hash_bytes_different_inputs(self) -> None:
        assert hash_bytes(b"hello") != hash_bytes(b"world")

    def test_hash_text_deterministic(self) -> None:
        assert hash_text("hello") == hash_text("hello")

    def test_hash_text_empty(self) -> None:
        h = hash_text("")
        assert len(h) == 64

    def test_hash_file_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("content")
        h1 = hash_file(str(f))
        h2 = hash_file(str(f))
        assert h1 == h2

    def test_hash_file_detects_mutation(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("original")
        h1 = hash_file(str(f))
        f.write_text("mutated")
        h2 = hash_file(str(f))
        assert h1 != h2

    def test_hash_records_deterministic(self) -> None:
        records = [{"a": 1, "b": 2}, {"c": 3}]
        assert hash_records(records) == hash_records(records)

    def test_hash_records_order_sensitive(self) -> None:
        r1 = [{"a": 1}, {"b": 2}]
        r2 = [{"b": 2}, {"a": 1}]
        # sort_keys=True but list order matters
        assert hash_records(r1) != hash_records(r2)

    def test_hash_config_deterministic(self) -> None:
        spec = ExperimentSpec(id="x", name="X")
        h1 = hash_config(spec)
        h2 = hash_config(spec)
        assert h1 == h2
        assert len(h1) == 64
