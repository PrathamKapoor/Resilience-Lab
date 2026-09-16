"""Immutable experiment artifact bundling with cryptographic hashing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resiliencelab.core.config import dump_yaml
from resiliencelab.core.policies import PolicyResolver, service_names
from resiliencelab.core.schema import POLICY_SCHEMA_VERSION
from resiliencelab.events import EVENT_SCHEMA_VERSION
from resiliencelab.experiments.provenance import hash_bytes, hash_file, hash_records, hash_text
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
        "policies": _policy_provenance(result),
        "metrics_per_run": result.metrics_per_run(),
        "service_metrics_per_run": result.service_metrics_per_run(),
        "seeds": result.seeds(),
        "repetitions": len(result.runs),
        "requested_repetitions": result.experiment.repetitions.count,
        "cancelled": result.cancelled,
        "cancellation_reason": result.cancellation_reason,
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

    all_events = []
    for index, run in enumerate(result.runs):
        event_lines = "\n".join(
            json.dumps(e.to_dict(), default=str, sort_keys=True) for e in run.events
        )
        record(f"raw/events-{index}.jsonl", event_lines.encode("utf-8"))
        all_events.extend(run.events)
    lifecycle_lines = "\n".join(
        json.dumps(e.to_dict(), default=str, sort_keys=True) for e in result.events
    )
    record("raw/events-experiment.jsonl", lifecycle_lines.encode("utf-8"))
    all_events.extend(result.events)
    events_hash = hash_text(
        json.dumps([e.to_dict() for e in all_events], sort_keys=True, default=str)
    )
    record("raw/events-hash.txt", f"{events_hash}\n".encode())

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
        "events_hash": events_hash,
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "event_count": len(all_events),
        "cancelled": result.cancelled,
        "cancellation_reason": result.cancellation_reason,
        "requested_repetitions": result.experiment.repetitions.count,
        "completed_repetitions": len(result.runs),
        "files": manifest_files,
    }
    _write_json(base / "manifest.json", manifest)
    return manifest


def verify_artifacts(base_dir: Path) -> dict[str, Any]:
    """Verify integrity of an artifact bundle against its manifest.

    Returns a dict with:
        - valid: bool — True only if every check passes
        - errors: list[str] — human-readable error descriptions
        - warnings: list[str] — non-fatal observations
        - manifest: dict — the loaded manifest
        - file_count: int — number of tracked files
        - verified_files: int — number of files that passed hash check
    """
    base = Path(base_dir)
    errors: list[str] = []
    warnings: list[str] = []

    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        return {
            "valid": False,
            "errors": ["manifest.json not found"],
            "warnings": [],
            "manifest": None,
            "file_count": 0,
            "verified_files": 0,
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tracked_files: dict[str, str] = manifest.get("files", {})

    verified = 0
    for rel_path, expected_hash in tracked_files.items():
        file_path = base / rel_path
        if not file_path.exists():
            errors.append(f"missing file: {rel_path}")
            continue
        actual_hash = hash_file(str(file_path))
        if actual_hash != expected_hash:
            errors.append(
                f"hash mismatch: {rel_path} expected={expected_hash} actual={actual_hash}"
            )
        else:
            verified += 1

    # Check for untracked files in key directories
    for subdir in ("raw", "analysis", "report"):
        dir_path = base / subdir
        if not dir_path.exists():
            continue
        for f in dir_path.iterdir():
            if f.is_file():
                rel = f"{subdir}/{f.name}"
                if rel not in tracked_files:
                    warnings.append(f"untracked file: {rel}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "manifest": manifest,
        "file_count": len(tracked_files),
        "verified_files": verified,
    }


def _policy_provenance(result: ExperimentResult) -> dict[str, Any]:
    spec = result.experiment
    resolver = PolicyResolver(spec.policy, spec.policies)
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "default": spec.policy.model_dump(mode="json"),
        "overrides": spec.policies,
        "resolved": {
            name: resolver.resolve(name).model_dump(mode="json") for name in service_names(spec)
        },
    }


def _build_statistics(result: ExperimentResult) -> dict[str, Any]:
    per_run = result.metrics_per_run()
    metrics: dict[str, list[float]] = {}
    for run in per_run:
        for key, value in run.items():
            metrics.setdefault(key, []).append(value)
    from resiliencelab.analysis.statistics import STAT_ANALYSIS_VERSION, summarize

    metric_summaries = {key: summarize(values) for key, values in metrics.items()}
    return {
        "analysis_version": STAT_ANALYSIS_VERSION,
        "resampling_unit": "repetition",
        "statistical_method": "t_mean_ci",
        "confidence_level": 0.95,
        "metrics": metric_summaries,
    }
