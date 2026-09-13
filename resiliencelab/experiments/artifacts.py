"""Immutable experiment artifact bundling with cryptographic hashing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resiliencelab.core.config import dump_yaml
from resiliencelab.experiments.provenance import hash_bytes, hash_records
from resiliencelab.experiments.report import build_report
from resiliencelab.experiments.result import ExperimentResult
from resiliencelab.metrics.collector import Record


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def write_artifacts(result: ExperimentResult, base_dir: Path) -> dict[str, Any]:
    base = Path(base_dir)
    raw_dir = base / "raw"
    analysis_dir = base / "analysis"
    report_dir = base / "report"
    for directory in (raw_dir, analysis_dir, report_dir):
        directory.mkdir(parents=True, exist_ok=True)

    manifest_files: dict[str, str] = {}

    def record(name: str, content: bytes) -> None:
        (base / name).write_bytes(content)
        manifest_files[name] = hash_bytes(content)

    record("configuration.yaml", dump_yaml(result.experiment).encode("utf-8"))
    record("environment.json", json.dumps(result.environment, indent=2).encode("utf-8"))

    summary = {
        "id": result.experiment.id,
        "name": result.experiment.name,
        "policy_name": result.policy_name,
        "config_hash": result.config_hash,
        "topology": [
            {"name": s.name, "depends_on": list(s.depends_on)}
            for s in result.experiment.system.services
        ],
        "metrics_per_run": result.metrics_per_run(),
        "service_metrics_per_run": result.service_metrics_per_run(),
    }
    record("experiment.json", json.dumps(summary, indent=2).encode("utf-8"))

    all_records: list[Record] = []
    for index, run in enumerate(result.runs):
        jsonl = "\n".join(json.dumps(r, default=str) for r in run.records)
        record(f"raw/records-{index}.jsonl", jsonl.encode("utf-8"))
        all_records.extend(run.records)
        _write_json(analysis_dir / f"timeline-{index}.json", run.timeline)

    raw_hash = hash_records(all_records)
    record("raw/records-hash.txt", f"{raw_hash}\n".encode())

    statistics = _build_statistics(result)
    _write_json(analysis_dir / "statistics.json", statistics)
    record("analysis/statistics.json", json.dumps(statistics, indent=2).encode("utf-8"))
    record("analysis/summary.json", json.dumps(summary, indent=2).encode("utf-8"))

    report_md = build_report(result)
    record("report/report.md", report_md.encode("utf-8"))

    manifest = {
        "experiment_id": result.experiment.id,
        "config_hash": result.config_hash,
        "raw_records_hash": raw_hash,
        "files": manifest_files,
    }
    _write_json(base / "manifest.json", manifest)
    return manifest


def _build_statistics(result: ExperimentResult) -> dict[str, Any]:
    per_run = result.metrics_per_run()
    metrics: dict[str, list[float]] = {}
    for run in per_run:
        for key, value in run.items():
            metrics.setdefault(key, []).append(value)
    from resiliencelab.analysis.statistics import summarize

    return {key: summarize(values) for key, values in metrics.items()}
