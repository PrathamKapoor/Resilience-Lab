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
    cancelled: bool = False
    cancellation_reason: str = ""

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

    def recovery_provenance(self) -> dict[str, Any]:
        """Structured recovery-gate provenance for audit/reproduction.

        Persists the gate decision inputs per repetition (which gates were
        evaluated, gate values, baselines, per-gate recovered flags) plus the
        gate parameters from the experiment analysis config needed to interpret
        the decision. Configuration itself is not duplicated beyond these
        thresholds.
        """
        analysis = self.experiment.analysis
        per_run: list[dict[str, Any]] = []
        for run in self.runs:
            r = run.recovery
            per_run.append(
                {
                    "run_id": run.run_id,
                    "seed": run.seed,
                    "degraded": r.degraded,
                    "degraded_at": r.degraded_at,
                    "recovered_at": r.recovered_at,
                    "time_to_recovery": r.time_to_recovery,
                    "time_to_degradation": r.time_to_degradation,
                    "degraded_duration": r.degraded_duration,
                    "gates_evaluated": list(r.gates_evaluated),
                    "latency_gate": r.latency_gate,
                    "baseline_throughput": r.baseline_throughput,
                    "baseline_p95_latency": r.baseline_p95_latency,
                    "latency_degraded": r.latency_degraded,
                    "latency_recovered": r.latency_recovered,
                }
            )
        baseline_window = analysis.baseline_window
        return {
            "thresholds": {
                "availability_threshold": analysis.availability_threshold,
                "latency_tolerance": analysis.latency_tolerance,
                "stability_window": float(analysis.stability_window),
                "baseline_window": float(baseline_window) if baseline_window is not None else None,
            },
            "stability_window": float(analysis.stability_window),
            "per_run": per_run,
        }

    def recovery_gate_line(self) -> str:
        """Concise human-readable recovery-gate decision for reports."""
        prov = self.recovery_provenance()
        per_run = prov["per_run"]
        stability = prov["stability_window"]
        n = len(per_run)
        if n == 0:
            return "Recovery gates: no runs"
        gates_union = sorted({g for r in per_run for g in r["gates_evaluated"]})
        n_recovered = sum(1 for r in per_run if r["recovered_at"] is not None)
        # Throughput PASS = recovered (throughput gate always evaluated when degraded).
        # Non-degraded runs (no gates, recovery 0.0) count as recovered without gate eval.
        parts: list[str] = []
        if "throughput" in gates_union:
            parts.append(f"throughput=PASS {n_recovered}/{n}")
        elif n_recovered == n:
            parts.append(f"throughput=PASS {n_recovered}/{n} (no degradation)")
        else:
            parts.append(f"throughput=FAIL {n_recovered}/{n}")
        if "latency" in gates_union:
            n_lat_pass = sum(1 for r in per_run if r["latency_recovered"])
            # Latency FAIL includes unrecovered plus recovered-but-latency-not-held.
            parts.append(f"latency={'PASS' if n_lat_pass == n else 'FAIL'} {n_lat_pass}/{n}")
        else:
            parts.append("latency=N/A")
        gates_str = ", ".join(parts)
        return (
            f"Recovery gates: {gates_str}, sustained {stability:.1f}s "
            f"(gates_evaluated={gates_union or []})"
        )

    def as_comparison_entry(self) -> dict[str, Any]:
        return {
            "id": self.experiment.id,
            "name": self.experiment.name,
            "policy_name": self.policy_name,
            "metrics_per_run": self.metrics_per_run(),
            "seeds": [run.seed for run in self.runs],
            "repetitions": len(self.runs),
        }
