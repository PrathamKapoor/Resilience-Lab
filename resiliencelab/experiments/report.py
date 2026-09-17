"""Human-readable report and automatic analysis generation."""

from __future__ import annotations

from resiliencelab.analysis.events import causal_trace, event_summary
from resiliencelab.analysis.statistics import summarize, summarize_censored
from resiliencelab.core.policies import PolicyResolver, service_names
from resiliencelab.core.schema import ExperimentSpec, PolicySpec
from resiliencelab.events import EventType
from resiliencelab.experiments.result import ExperimentResult
from resiliencelab.metrics.transforms import latency_components


def _fmt(value: float, ndigits: int = 4) -> str:
    if value == float("inf"):
        return "inf"
    if value != value:
        return "nan"
    return f"{value:.{ndigits}f}"


def _summary_line(label: str, values: list[float]) -> str:
    stats = summarize(values)
    if "mean" not in stats or stats.get("count", 0) == 0:
        return f"- **{label}**: no data"
    n = int(stats.get("count", 0))
    note = "" if n >= 2 else " (insufficient replicates for inference)"
    return (
        f"- **{label}**: mean={_fmt(stats['mean'])}, "
        f"95% CI [{_fmt(stats['ci_low'])}, {_fmt(stats['ci_high'])}], n={n}{note}"
    )


def _censored_summary_line(label: str, values: list[float]) -> str:
    stats = summarize_censored(values)
    n = int(stats.get("count", 0))
    if n == 0 or "mean" not in stats:
        return f"- **{label}**: no data"
    recovered = int(stats.get("n_recovered", n))
    rate = float(stats.get("recovery_rate", 1.0))
    if recovered == 0:
        return f"- **{label}**: unrecovered in all {n} run(s) (recovery rate 0.0)"
    if recovered < n:
        return (
            f"- **{label}**: mean={_fmt(float(stats['mean']))} over {recovered}/{n} recovered "
            f"(recovery rate {rate:.2f}), 95% CI [{_fmt(float(stats['ci_low']))}, "
            f"{_fmt(float(stats['ci_high']))}]"
        )
    return _summary_line(label, values)


def _statistical_provenance(result: ExperimentResult) -> str:
    return (
        "Analysis: repetition-level means with 95% t-based CI (resampling unit = "
        "repetition; bootstrap available opt-in); seeded decisions deterministic "
        "(Layer A), wall-clock execution varies (Layer B); analyses key off "
        "`analysis_version` in artifacts."
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
        _summary_line("p95 latency (s)", p95),
        _summary_line("p99 latency (s)", p99),
        _summary_line("error rate", error_rate),
        _summary_line("failure amplification", amplification),
        _censored_summary_line("time to recovery (s)", recovery),
        "",
        "Statistical confidence: 95% t-based confidence intervals reported for primary metrics "
        "(repetition unit; n=5 gives wide intervals; unrecovered runs reported as inf with recovery rate).",
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


def _describe_policy(spec: PolicySpec) -> str:
    parts: list[str] = []
    if spec.retry is not None:
        parts.append(f"retry(max_attempts={spec.retry.max_attempts})")
    else:
        parts.append("retry=disabled")
    if spec.retry is not None:
        backoff = spec.backoff
        parts.append(
            f"backoff({backoff.type.value}, base={backoff.base}s, jitter={backoff.jitter.value})"
        )
    if spec.circuit_breaker is not None:
        cb = spec.circuit_breaker
        parts.append(f"circuit_breaker(threshold={cb.threshold}, recovery={cb.recovery_window}s)")
    else:
        parts.append("circuit_breaker=disabled")
    if spec.timeout is not None and (
        spec.timeout.connect is not None
        or spec.timeout.read is not None
        or spec.timeout.total is not None
    ):
        parts.append(f"timeout(total={spec.timeout.total}s)")
    if spec.concurrency is not None:
        concurrency = spec.concurrency
        parts.append(
            f"concurrency(limit={concurrency.limit}, queue_limit={concurrency.queue_limit})"
        )
    return ", ".join(parts) if parts else "baseline"


def _service_policies_section(result: ExperimentResult) -> str:
    spec = result.experiment
    resolver = PolicyResolver(spec.policy, spec.policies)
    lines = ["## Service policies", ""]
    for name in service_names(spec):
        lines.append(f"- **{name}**: {_describe_policy(resolver.resolve(name))}")
    if spec.policies:
        lines.append("")
        lines.append("Per-service overrides present for: " + ", ".join(sorted(spec.policies)))
    return "\n".join(lines)


def _observability_section(result: ExperimentResult) -> str:
    events = result.run_events()
    counts = event_summary(events)
    if not events:
        return "\n".join(["## Observability summary", "", "No events recorded."])

    tracked = {
        "requests": [
            EventType.REQUEST_STARTED,
            EventType.REQUEST_COMPLETED,
            EventType.REQUEST_FAILED,
        ],
        "dependencies": [
            EventType.DEPENDENCY_CALLED,
            EventType.DEPENDENCY_COMPLETED,
            EventType.DEPENDENCY_FAILED,
        ],
        "retries": [EventType.RETRY_SCHEDULED, EventType.RETRY_EXECUTED],
        "timeouts": [EventType.TIMEOUT_TRIGGERED],
        "breaker": [
            EventType.CIRCUIT_OPENED,
            EventType.CIRCUIT_HALF_OPENED,
            EventType.CIRCUIT_CLOSED,
        ],
        "capacity": [
            EventType.SERVICE_REQUEST_QUEUED,
            EventType.SERVICE_REQUEST_REJECTED,
            EventType.SERVICE_SATURATED,
            EventType.SERVICE_RECOVERED,
        ],
        "faults": [EventType.FAULT_INJECTED, EventType.FAULT_RECOVERED],
    }
    lines = ["## Observability summary", "", f"Events: {len(events)}", ""]
    for label, types in tracked.items():
        total = sum(counts.get(t.value, 0) for t in types)
        if total == 0:
            continue
        parts = [
            f"{t.value.replace('Circuit', '').replace('ServiceRequest', '')}: {counts.get(t.value, 0)}"
            for t in types
        ]
        lines.append(f"{label}: " + ", ".join(parts))

    if result.runs:
        lines += [
            "",
            "## Causal timeline (sample)",
            "",
            "```",
            causal_trace(result.runs[0].events, limit=25),
            "```",
        ]
    return "\n".join(lines)


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
        _service_policies_section(result),
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
        if metric == "recovery_time":
            sections.append(_censored_summary_line(metric, values))
        else:
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
        f"- **network latency**: {_fmt(components.get('network', 0.0))}s mean simulated per-call delay.",
        f"- **processing latency**: {_fmt(components.get('processing', 0.0))}s mean simulated service processing.",
        f"- **queue wait**: {_fmt(components.get('queue', 0.0))}s mean wall-clock queue wait.",
        "",
        "Throughput is requests per second over the measured (post-warmup) window.",
        "Amplification is downstream calls per upstream request.",
        "",
        _service_capacity_section(result),
        "",
        _observability_section(result),
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
