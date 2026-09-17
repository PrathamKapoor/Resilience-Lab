"""Authoritative benchmark catalog, derived mechanically from benchmark YAMLs.

The YAML files under ``benchmarks/`` are the source of truth for experiment
configuration. This module adds the research layer (hypothesis, research
question mapping, expected metrics, factorial factors, status) and validates
that documentation references agree with the actual catalog.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from resiliencelab.core.config import load_yaml

RESEARCH_MAPPING: dict[str, dict[str, Any]] = {
    "RL-BENCH-001": {
        "hypothesis": "Retries with exponential backoff preserve availability under intermittent 503s.",
        "research_questions": ["RQ1", "RQ2"],
        "expected_metrics": ["availability", "latency_p95", "amplification"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-002": {
        "hypothesis": "Timeouts bound tail latency under injected latency degradation.",
        "research_questions": ["RQ1", "RQ2"],
        "expected_metrics": ["latency_p95", "latency_p99", "timeout_rate"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-003": {
        "hypothesis": "Retries plus circuit breaking shorten outage degradation and recovery.",
        "research_questions": ["RQ1", "RQ5"],
        "expected_metrics": ["availability", "recovery_time"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-004": {
        "hypothesis": "Client-side concurrency limits contain client overload when the dependency adds saturation delay.",
        "research_questions": ["RQ1"],
        "expected_metrics": ["throughput", "latency_p95", "error_rate"],
        "factors": None,
        "status": "stable",
        "note": "Exercises client-side concurrency plus the saturation-delay fault, not service-side capacity.",
    },
    "RL-BENCH-005": {
        "hypothesis": "Aggressive fixed-backoff retries amplify downstream load during a burst outage.",
        "research_questions": ["RQ4"],
        "expected_metrics": ["amplification", "availability"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-006": {
        "hypothesis": "Staged faults across payment/inventory reveal short-circuit sparing of downstream calls.",
        "research_questions": ["RQ2", "RQ5"],
        "expected_metrics": ["availability", "error_rate"],
        "factors": None,
        "status": "stable",
        "note": "SUT short-circuits on first failure, sparing downstream services.",
    },
    "RL-BENCH-007": {
        "hypothesis": "Recovery time after restoration is measurable with explicit thresholds.",
        "research_questions": ["RQ5"],
        "expected_metrics": ["recovery_time"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-008": {
        "hypothesis": "Policies degrade gracefully when failure type changes mid-run.",
        "research_questions": ["RQ2"],
        "expected_metrics": ["availability", "latency_p95"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-009": {
        "hypothesis": "Simulated processing latency shifts client latency without faults.",
        "research_questions": ["RQ1"],
        "expected_metrics": ["latency_p95", "throughput"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-010": {
        "hypothesis": "Simulated network delay/jitter interacts with client timeouts.",
        "research_questions": ["RQ1", "RQ6"],
        "expected_metrics": ["latency_p95", "timeout_rate"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-011": {
        "hypothesis": "Fixed service capacity saturates under closed-loop arrival load.",
        "research_questions": ["RQ1", "RQ4"],
        "expected_metrics": ["throughput", "error_rate"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-012": {
        "hypothesis": "Retries increase downstream pressure against a saturated dependency.",
        "research_questions": ["RQ3", "RQ4"],
        "expected_metrics": ["amplification", "availability"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-013": {
        "hypothesis": "Per-service retry overrides isolate dependency behavior (event-level).",
        "research_questions": ["RQ1"],
        "expected_metrics": ["availability", "amplification"],
        "factors": None,
        "status": "stable",
        "note": "Isolation visible in events/service behavior; primary metrics are global.",
    },
    "RL-BENCH-014": {
        "hypothesis": "Per-service breaker/retry state isolates burst-outage impact (event-level).",
        "research_questions": ["RQ1"],
        "expected_metrics": ["availability", "error_rate"],
        "factors": None,
        "status": "stable",
        "note": "Isolation visible in events/service behavior; primary metrics are global.",
    },
    "RL-BENCH-015": {
        "hypothesis": "Failure to retry scheduling to outcome is reconstructable from events.",
        "research_questions": ["RQ1"],
        "expected_metrics": ["amplification"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-016": {
        "hypothesis": "Queueing/saturation/rejection/recovery is observable as structured events.",
        "research_questions": ["RQ5"],
        "expected_metrics": ["recovery_time", "error_rate"],
        "factors": None,
        "status": "stable",
    },
    "RL-BENCH-017": {
        "hypothesis": "Policy main effects and policy x fault interactions are estimable via matrix expansion.",
        "research_questions": ["RQ3"],
        "expected_metrics": ["availability", "latency_p95"],
        "factors": "matrix expansion required (single-cell base config)",
        "status": "base-config",
        "note": "YAML is the base cell; run `matrix` to expand the factorial design.",
    },
    "RL-BENCH-018": {
        "hypothesis": "Retry x capacity interactions show when retries help vs amplify saturation.",
        "research_questions": ["RQ3", "RQ4"],
        "expected_metrics": ["availability", "amplification"],
        "factors": "matrix expansion required (single-cell base config)",
        "status": "base-config",
        "note": "YAML is the base cell; run `matrix` to expand the factorial design.",
    },
}

PAPER_BENCHMARK_IDS = sorted(RESEARCH_MAPPING)


def default_benchmarks_dir() -> Path:
    return Path("benchmarks")


def load_catalog(benchmarks_dir: str | Path | None = None) -> list[dict[str, Any]]:
    directory = Path(benchmarks_dir) if benchmarks_dir else default_benchmarks_dir()
    entries: list[dict[str, Any]] = []
    for path in sorted(directory.glob("RL-BENCH-*.yaml")):
        spec = load_yaml(path)
        research = RESEARCH_MAPPING.get(spec.id, {})
        entries.append(
            {
                "id": spec.id,
                "name": spec.name,
                "description": spec.description,
                "path": str(path),
                "workload": spec.workload.type.value,
                "clients": spec.workload.clients,
                "failures": [
                    {"target": f.target, "type": f.type.value, "mode": f.mode.value}
                    for f in spec.failure
                ],
                "repetitions": spec.repetitions.count,
                "base_seed": spec.repetitions.base_seed,
                "hypothesis": research.get("hypothesis", ""),
                "research_questions": research.get("research_questions", []),
                "expected_metrics": research.get("expected_metrics", []),
                "factors": research.get("factors"),
                "status": research.get("status", "stable"),
                "note": research.get("note", ""),
            }
        )
    return entries


def validate_catalog(entries: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids = [e["id"] for e in entries]
    if len(set(ids)) != len(ids):
        errors.append("duplicate benchmark IDs in catalog")
    for entry in entries:
        if not entry["hypothesis"]:
            errors.append(f"{entry['id']}: missing hypothesis mapping")
        if not entry["research_questions"]:
            errors.append(f"{entry['id']}: missing research-question mapping")
        if entry["repetitions"] < 1:
            errors.append(f"{entry['id']}: repetitions must be >= 1")
    documented = set(RESEARCH_MAPPING)
    actual = set(ids)
    if documented != actual:
        errors.append(
            f"catalog mapping drift: mapping={sorted(documented)} actual={sorted(actual)}"
        )
    for paper_id in PAPER_BENCHMARK_IDS:
        if paper_id not in actual:
            errors.append(f"paper benchmark {paper_id} missing from catalog")
    return errors
