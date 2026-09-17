"""F-M3 regression: malformed YAML must surface as ConfigValidationError."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from resiliencelab.cli.app import app
from resiliencelab.core.config import ConfigValidationError, load_yaml
from resiliencelab.experiments.catalog import load_catalog

RUNNER = CliRunner()
MALFORMED = "experiment:\n  id: [unclosed\n  name: bad\n: : :\n"
MALFORMED_NESTED = (
    "experiment:\n  id: nestedbad\n  name: nestedbad\nworkload:\n  type: closed_loop\n"
    "  clients: [oops\n    broken: : :\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_yaml_malformed_raises_public_error(tmp_path: Path) -> None:
    target = _write(tmp_path / "bad.yaml", MALFORMED)
    with pytest.raises(ConfigValidationError):
        load_yaml(target)
    # Raw parser exception must not escape.
    try:
        load_yaml(target)
    except ConfigValidationError:
        pass
    except yaml.YAMLError as exc:  # pragma: no cover
        pytest.fail(f"raw YAMLError escaped: {exc}")


def test_load_yaml_malformed_nested_raises_public_error(tmp_path: Path) -> None:
    target = _write(tmp_path / "nestedbad.yaml", MALFORMED_NESTED)
    with pytest.raises(ConfigValidationError):
        load_yaml(target)


def test_validate_cli_reports_error_not_traceback(tmp_path: Path) -> None:
    target = _write(tmp_path / "bad.yaml", MALFORMED)
    result = RUNNER.invoke(app, ["validate", str(target)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "invalid YAML" in result.output or "error" in result.output.lower()


def test_run_cli_reports_error_not_traceback(tmp_path: Path) -> None:
    target = _write(tmp_path / "bad.yaml", MALFORMED)
    result = RUNNER.invoke(app, ["run", str(target), "--store", str(tmp_path / "results")])
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_benchmark_cli_malformed_reports_error(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    _write(bench_dir / "RL-BENCH-001.yaml", MALFORMED)
    result = RUNNER.invoke(
        app,
        ["benchmark", "RL-BENCH-001", "--benchmarks-dir", str(bench_dir)],
    )
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_reproduce_all_malformed_recorded_not_raised(tmp_path: Path) -> None:
    from resiliencelab.experiments.reproduce import reproduce_all

    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    _write(bench_dir / "RL-BENCH-001.yaml", MALFORMED)
    manifest = reproduce_all(
        tmp_path / "results",
        benchmarks_dir=str(bench_dir),
        benchmarks=["RL-BENCH-001"],
    )
    assert manifest["failed"] == 1
    assert manifest["results"][0]["status"] == "failed"
    assert "invalid" in manifest["results"][0]["error"].lower()


def test_catalog_malformed_raises_public_error(tmp_path: Path) -> None:
    _write(tmp_path / "RL-BENCH-001.yaml", MALFORMED)
    with pytest.raises(ConfigValidationError):
        load_catalog(tmp_path)
