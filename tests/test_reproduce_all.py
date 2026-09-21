"""C2 regression: `reproduce --all` must be coherent and honest."""

from __future__ import annotations

import json
from pathlib import Path

import click
from typer.testing import CliRunner

from resiliencelab.cli.app import app
from resiliencelab.experiments.reproduce import reproduce_all

RUNNER = CliRunner()


def _tiny_benchmark(directory: Path, bench_id: str) -> None:
    (directory / f"{bench_id}.yaml").write_text(
        "\n".join(
            [
                "experiment:",
                f"  id: {bench_id}",
                f"  name: {bench_id.lower()}",
                "  version: 1",
                "workload:",
                "  type: closed_loop",
                "  clients: 2",
                "  duration: 0.3s",
                "failure: []",
                "policy: {}",
                "repetitions:",
                "  count: 1",
                "  base_seed: 5",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_reproduce_all_help_mentions_all() -> None:
    result = RUNNER.invoke(app, ["reproduce", "--help"])
    assert result.exit_code == 0
    # Typer forces styled output when GITHUB_ACTIONS is set, which splits "--all"
    # across ANSI escape codes; compare against the unstyled text.
    assert "--all" in click.unstyle(result.output)


def test_reproduce_all_success_writes_manifest_and_artifacts(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    _tiny_benchmark(bench_dir, "RL-BENCH-001")
    _tiny_benchmark(bench_dir, "RL-BENCH-002")
    store = tmp_path / "results"
    manifest = reproduce_all(
        store,
        benchmarks_dir=str(bench_dir),
        benchmarks=["RL-BENCH-001", "RL-BENCH-002"],
    )
    assert manifest["succeeded"] == 2
    assert manifest["failed"] == 0
    manifest_path = store / "reproduction_manifest.json"
    assert manifest_path.exists()
    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk["succeeded"] == 2
    for bench_id in ("RL-BENCH-001", "RL-BENCH-002"):
        assert (store / bench_id / "manifest.json").exists()
        assert (store / bench_id / "configuration.yaml").exists()


def test_reproduce_all_missing_experiment_recorded(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    manifest = reproduce_all(
        tmp_path / "results",
        benchmarks_dir=str(bench_dir),
        benchmarks=["RL-BENCH-999"],
    )
    assert manifest["failed"] == 1
    assert manifest["results"][0]["status"] == "missing"


def test_reproduce_all_partial_success_and_failure(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    _tiny_benchmark(bench_dir, "RL-BENCH-001")
    manifest = reproduce_all(
        tmp_path / "results",
        benchmarks_dir=str(bench_dir),
        benchmarks=["RL-BENCH-001", "RL-BENCH-999"],
    )
    assert manifest["succeeded"] == 1
    assert manifest["failed"] == 1


def test_reproduce_all_corrupt_artifact_detected(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    _tiny_benchmark(bench_dir, "RL-BENCH-001")
    store = tmp_path / "results"
    first = reproduce_all(store, benchmarks_dir=str(bench_dir), benchmarks=["RL-BENCH-001"])
    assert first["succeeded"] == 1
    target = store / "RL-BENCH-001" / "report" / "report.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nINJECTED\n", encoding="utf-8")
    from resiliencelab.experiments.artifacts import verify_artifacts

    verification = verify_artifacts(store / "RL-BENCH-001")
    assert verification["valid"] is False


def test_reproduce_all_failed_experiment_recorded(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    (bench_dir / "RL-BENCH-001.yaml").write_text(
        "experiment:\n  id: bad\n  name: bad\nworkload:\n  type: closed_loop\n"
        "  clients: 0\n  duration: 0.3s\n",
        encoding="utf-8",
    )
    manifest = reproduce_all(
        tmp_path / "results",
        benchmarks_dir=str(bench_dir),
        benchmarks=["RL-BENCH-001"],
    )
    assert manifest["failed"] == 1
    assert manifest["results"][0]["status"] == "failed"


def test_reproduce_all_cli_exit_code_on_missing(tmp_path: Path, monkeypatch) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    result = RUNNER.invoke(
        app,
        [
            "reproduce",
            "--all",
            "--store",
            str(tmp_path / "results"),
            "--benchmarks-dir",
            str(bench_dir),
        ],
    )
    # No declared benchmarks resolve in an empty dir -> non-zero exit
    assert result.exit_code != 0


def test_reproduce_all_deterministic_config_reconstruction(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    _tiny_benchmark(bench_dir, "RL-BENCH-001")
    store = tmp_path / "results"
    reproduce_all(store, benchmarks_dir=str(bench_dir), benchmarks=["RL-BENCH-001"])
    first_hash = json.loads((store / "RL-BENCH-001" / "manifest.json").read_text())["config_hash"]
    reproduce_all(store, benchmarks_dir=str(bench_dir), benchmarks=["RL-BENCH-001"])
    second_hash = json.loads((store / "RL-BENCH-001" / "manifest.json").read_text())["config_hash"]
    assert first_hash == second_hash
