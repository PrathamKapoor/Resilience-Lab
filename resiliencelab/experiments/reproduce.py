"""Paper-scale reproduction: rerun declared benchmarks and verify artifacts.

No fake figures or tables are produced. Reproduction means: for each declared
benchmark, resolve its YAML, rerun it, persist a full artifact bundle, verify
the bundle against its manifest, and record a machine-readable reproduction
manifest. Statistical summaries come from the persisted
``analysis/statistics.json`` and matrix comparison files.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from resiliencelab.core.config import ConfigValidationError, load_yaml
from resiliencelab.experiments.artifacts import verify_artifacts, write_artifacts
from resiliencelab.experiments.benchmarks import (
    list_standard_benchmarks,
    normalize_benchmark_name,
    resolve_benchmark_path,
)
from resiliencelab.experiments.runner import ExperimentRunner


def reproduce_all(
    store: Path | str,
    benchmarks_dir: str | None = None,
    repetitions: int | None = None,
    benchmarks: list[str] | None = None,
) -> dict[str, Any]:
    store_root = Path(store)
    names = benchmarks if benchmarks is not None else list_standard_benchmarks()
    runner = ExperimentRunner()
    results: list[dict[str, Any]] = []
    for raw_name in names:
        name = normalize_benchmark_name(raw_name)
        entry: dict[str, Any] = {"id": name, "status": "pending"}
        path = resolve_benchmark_path(name, benchmarks_dir)
        if path is None:
            entry["status"] = "missing"
            entry["error"] = f"benchmark YAML not found for `{name}`"
            results.append(entry)
            continue
        try:
            spec = load_yaml(path)
        except (ConfigValidationError, OSError) as exc:
            entry["status"] = "failed"
            entry["error"] = f"invalid configuration: {exc}"
            results.append(entry)
            continue
        if repetitions is not None:
            spec.repetitions.count = repetitions
        try:
            result = runner.run(spec)
        except Exception as exc:  # noqa: BLE001
            entry["status"] = "failed"
            entry["error"] = f"execution failed: {exc}"
            results.append(entry)
            continue
        dest = store_root / spec.id
        try:
            manifest = write_artifacts(result, dest)
        except Exception as exc:  # noqa: BLE001
            entry["status"] = "failed"
            entry["error"] = f"artifact write failed: {exc}"
            results.append(entry)
            continue
        verification = verify_artifacts(dest)
        entry["status"] = "ok" if verification["valid"] else "corrupt"
        entry["artifact_dir"] = str(dest)
        entry["config_hash"] = manifest.get("config_hash")
        entry["verification"] = {
            "valid": verification["valid"],
            "errors": verification["errors"],
            "warnings": verification["warnings"],
            "verified_files": verification["verified_files"],
            "file_count": verification["file_count"],
        }
        if not verification["valid"]:
            entry["error"] = "; ".join(verification["errors"])
        results.append(entry)
    succeeded = sum(1 for r in results if r["status"] == "ok")
    failed = len(results) - succeeded
    manifest_doc: dict[str, Any] = {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "store": str(store_root),
        "benchmarks_dir": benchmarks_dir,
        "repetitions_override": repetitions,
        "benchmarks": names,
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }
    store_root.mkdir(parents=True, exist_ok=True)
    (store_root / "reproduction_manifest.json").write_text(
        __import__("json").dumps(manifest_doc, indent=2, default=str), encoding="utf-8"
    )
    return manifest_doc
