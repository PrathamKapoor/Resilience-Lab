"""Aggregation and transforms over collected observation records."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median

from resiliencelab.metrics.collector import MetricsCollector, Record


def _pct(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    index = p * (n - 1)
    lower = int(index)
    upper = min(lower + 1, n - 1)
    frac = index - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def percentiles(values: list[float], ps: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {f"p{int(p * 1000) / 10:g}".replace(".0", ""): _pct(ordered, p) for p in ps}


def requests(records: list[Record]) -> list[Record]:
    return [r for r in records if r.get("kind") == MetricsCollector.REQUEST]


def downstreams(records: list[Record]) -> list[Record]:
    return [r for r in records if r.get("kind") == MetricsCollector.DOWNSTREAM]


def events(records: list[Record]) -> list[Record]:
    return [r for r in records if r.get("kind") == MetricsCollector.EVENT]


def request_latencies(records: list[Record]) -> list[float]:
    return [r["latency"] for r in requests(records) if r.get("latency") is not None]


def downstream_latencies(records: list[Record]) -> list[float]:
    return [r["latency"] for r in downstreams(records) if r.get("latency") is not None]


def throughput_series(records: list[Record], bucket: float = 1.0) -> list[tuple[float, float]]:
    reqs = requests(records)
    if not reqs:
        return []
    t0 = min(r["t"] for r in reqs)
    t1 = max(r["t"] for r in reqs)
    if t1 <= t0:
        return [(t0, float(len(reqs)))]
    buckets: dict[int, int] = {}
    for r in reqs:
        idx = int((r["t"] - t0) / bucket)
        buckets[idx] = buckets.get(idx, 0) + 1
    return [
        (t0 + i * bucket + bucket / 2, buckets.get(i, 0) / bucket)
        for i in range(int((t1 - t0) / bucket) + 1)
    ]


def failure_amplification(records: list[Record]) -> float:
    reqs = requests(records)
    if not reqs:
        return 0.0
    return len(downstreams(records)) / len(reqs)


@dataclass
class RequestSummary:
    total: int = 0
    successful: int = 0
    failed: int = 0
    timeouts: int = 0
    availability: float = 0.0
    error_rate: float = 0.0
    timeout_rate: float = 0.0
    throughput: float = 0.0
    latency_mean: float = 0.0
    latency_median: float = 0.0
    latency_p90: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    latency_p999: float = 0.0
    latency_max: float = 0.0
    amplifications: dict[str, float] = field(default_factory=dict)


def summarize_requests(records: list[Record]) -> RequestSummary:
    reqs = requests(records)
    summary = RequestSummary()
    summary.total = len(reqs)
    if not reqs:
        return summary
    successes = [r for r in reqs if r.get("success")]
    summary.successful = len(successes)
    summary.failed = summary.total - summary.successful
    summary.timeouts = sum(1 for r in reqs if r.get("timeout"))
    summary.availability = summary.successful / summary.total
    summary.error_rate = summary.failed / summary.total
    summary.timeout_rate = summary.timeouts / summary.total

    latencies = request_latencies(records)
    if latencies:
        summary.latency_mean = mean(latencies)
        summary.latency_median = median(latencies)
        summary.latency_max = max(latencies)
        p = percentiles(latencies, [0.9, 0.95, 0.99, 0.999])
        summary.latency_p90 = p["p90"]
        summary.latency_p95 = p["p95"]
        summary.latency_p99 = p["p99"]
        summary.latency_p999 = p["p99.9"]

    t0 = min(r["t"] for r in reqs)
    t1 = max(r["t"] for r in reqs)
    if t1 > t0:
        summary.throughput = summary.total / (t1 - t0)
    summary.amplifications["requests"] = failure_amplification(records)
    return summary


def summarize_downstream(records: list[Record]) -> dict[str, float]:
    ds = downstreams(records)
    if not ds:
        return {"total": 0.0, "successful": 0.0, "failed": 0.0}
    ok = sum(1 for r in ds if r.get("success"))
    lat = downstream_latencies(records)
    return {
        "total": float(len(ds)),
        "successful": float(ok),
        "failed": float(len(ds) - ok),
        "latency_mean": mean(lat) if lat else 0.0,
        "latency_p99": _pct(sorted(lat), 0.99) if lat else 0.0,
    }
