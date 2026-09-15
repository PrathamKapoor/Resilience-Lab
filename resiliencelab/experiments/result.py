"""Typed experiment results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from resiliencelab.analysis.recovery import RecoveryReport
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.events import Event
from resiliencelab.metrics.collector import Record
from resiliencelab.metrics.transforms import RequestSummary


@dataclass
class RunResult:
    run_id: str
    seed: int
    summary: RequestSummary
    downstream: dict[str, float]
    recovery: RecoveryReport
    timeline: list[Record]
    record_count: int
    backoff_seconds: float
    records: list[Record] = field(default_factory=list)
    service_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    def primary_metrics(self) -> dict[str, float]:
        recovery_time = self.recovery.time_to_recovery
        return {
            "availability": self.summary.availability,
            "throughput": self.summary.throughput,
            "latency_mean": self.summary.latency_mean,
            "latency_p95": self.summary.latency_p95,
            "latency_p99": self.summary.latency_p99,
            "latency_p999": self.summary.latency_p999,
            "amplification": self.summary.amplifications.get("requests", 0.0),
            "recovery_time": recovery_time,
            "error_rate": self.summary.error_rate,
            "timeout_rate": self.summary.timeout_rate,
        }


@dataclass
class ExperimentResult:
    experiment: ExperimentSpec
    policy_name: str
    config_hash: str
    runs: list[RunResult]
    environment: dict[str, str] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    @property
    def experiment_id(self) -> str:
        return self.experiment.id

    def metrics_per_run(self) -> list[dict[str, float]]:
        return [run.primary_metrics() for run in self.runs]

    def service_metrics_per_run(self) -> list[dict[str, dict[str, float]]]:
        return [run.service_metrics for run in self.runs]

    def run_events(self) -> list[Event]:
        return [event for run in self.runs for event in run.events]

    def seeds(self) -> list[int]:
        return [run.seed for run in self.runs]

    def as_comparison_entry(self) -> dict[str, Any]:
        return {
            "id": self.experiment.id,
            "name": self.experiment.name,
            "policy_name": self.policy_name,
            "metrics_per_run": self.metrics_per_run(),
            "seeds": [run.seed for run in self.runs],
            "repetitions": len(self.runs),
        }
