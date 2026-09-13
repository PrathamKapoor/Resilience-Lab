"""Human-readable report and automatic analysis generation."""

from __future__ import annotations

from resiliencelab.analysis.statistics import summarize
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.result import ExperimentResult
from resiliencelab.metrics.transforms import latency_components


def _fmt(value: float, ndigits: int = 4) -> str:
    if value == float("inf"):
        return "inf"
    if value != value:
        return "nan"
    return f"{value:.{ndigits}f}"


def _summary_line(label: str, values: list[float], higher_is_better: bool = True) -> str:
    stats = summarize(values)
    if "mean" not in stats:
        return f"- **{label}**: no data"
    return (
        f"- **{label}**: mean={_fmt(stats['mean'])} "
        f"(95% CI [{_fmt(stats['ci_low'])}, {_fmt(stats['ci_high'])}])"
    )


def automatic_analysis(result: ExperimentResult) -> str:
    runs = result.runs
    if not runs:
        return "No runs recorded."
    availability = [r.summary.availability for r in runs]
    p95 = [r.summary.latency_p95 for r in runs]
    p99 = [r.summary.latency_p99 for r in runs]
    amplification = [r.summary.amplifications.get("requests", 0.0) for r in runs]
    error_rate = [r.summary.error_rate for r in runs]
    recovery = [r.recovery.time_to_recovery for r in runs]

    lines = [
        "RESULT SUMMARY",
        "",
        f"Policy: {result.policy_name}",
        "",
        "Observed (mean over repetitions, 95% CI reported):",
        _summary_line("availability", availability),
        _summary_line("p95 latency (s)", p95, higher_is_better=False),
        _summary_line("p99 latency (s)", p99, higher_is_better=False),
        _summary_line("error rate", error_rate, higher_is_better=False),
        _summary_line("failure amplification", amplification, higher_is_better=False),
        _summary_line("time to recovery (s)", recovery, higher_is_better=False),
        "",
        "Statistical confidence: 95% confidence intervals reported for primary metrics.",
        "",
        "Recommendation: see comparison and interaction analysis for evidence-based ranking.",
    ]
    return "\n".join(lines)


def _topology_line(spec: ExperimentSpec) -> str:
    if not spec.system.services:
        return "services: [payment_service (default single dependency)]"
    described = [
        s.name + (f" (depends_on={','.join(s.depends_on)})" if s.depends_on else "")
        for s in spec.system.services
    ]
    return f"services: {described}"


def build_report(result: ExperimentResult) -> str:
    spec = result.experiment
    sections = [
        f"# Experiment Report: {spec.name}",
        "",
        f"- **Experiment ID**: `{spec.id}`",
        f"- **Policy**: {result.policy_name}",
        f"- **Config SHA256**: `{result.config_hash}`",
        f"- **Repetitions**: {len(result.runs)}",
        "",
        "## Configuration",
        "```",
        f"failure targets: {[f.target for f in spec.failure]}",
        f"failure kinds: {[f.type.value for f in spec.failure]}",
        _topology_line(spec),
        f"workload: {spec.workload.type.value}, {spec.workload.clients} clients",
        "```",
        "",
        "## Results",
    ]
    metrics_per_run = result.metrics_per_run()
    for metric in [
        "availability",
        "throughput",
        "latency_p95",
        "latency_p99",
        "amplification",
        "recovery_time",
        "error_rate",
        "timeout_rate",
    ]:
        values = [m[metric] for m in metrics_per_run]
        sections.append(_summary_line(metric, values))
    components = latency_components([r for run in result.runs for r in run.records])
    sections += [
        "",
        "## Measurement semantics",
        "",
        "Latency is total wall-clock time (seconds) from request issue to response or",
        "exception. It decomposes into:",
        f"- **service time**: {_fmt(components['service'])}s mean simulated dependency",
        "  processing across attempts (fault/saturation delay included).",
        f"- **backoff wait**: {_fmt(components['retry'])}s mean scheduled retry backoff.",
        f"- **other (queue/timeout/scheduling)**: {_fmt(components['other'])}s = total - "
        "service - backoff.",
        "",
        "Simulated sub-components of service time (see docs/simulation.md):",
        f"- **network latency**: {_fmt(components['network'])}s mean simulated per-call delay.",
        f"- **processing latency**: {_fmt(components['processing'])}s mean simulated service processing.",
        f"- **queue wait**: {_fmt(components['queue'])}s mean wall-clock queue wait.",
        "",
        "Throughput is requests per second over the measured (post-warmup) window.",
        "Amplification is downstream calls per upstream request.",
        "",
        _service_capacity_section(result),
        "## Automatic Analysis",
        "",
        automatic_analysis(result),
        "",
    ]
    return "\n".join(sections)


def _service_capacity_section(result: ExperimentResult) -> str:
    lines: list[str] = ["## Simulated service capacity"]
    runs = result.service_metrics_per_run()
    names = sorted({name for run in runs for name in run})
    if not names:
        return "\n".join(lines + ["No per-service capacity configured."])
    for name in names:
        snapshots = [run[name] for run in runs if name in run]
        if not snapshots:
            continue
        capacity = snapshots[0].get("capacity", 0.0)
        peak_queue = max(s.get("peak_queue_depth", 0.0) for s in snapshots)
        rejected = sum(s.get("rejected_count", 0.0) for s in snapshots)
        lines.append(
            f"- **{name}**: capacity={capacity:.0f}, peak queue depth={peak_queue:.0f}, "
            f"service-side rejections={rejected:.0f} (over {len(snapshots)} run(s))"
        )
    return "\n".join(lines)
