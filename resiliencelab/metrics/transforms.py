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


def latency_components(records: list[Record]) -> dict[str, float]:
    """Decompose mean request latency into its measured components.

    Definitions (all in seconds, wall-clock):

    - ``total``:   mean ``request.latency`` — full time from request issue to
      response or exception.
    - ``service``: mean per-request sum of ``downstream.latency`` — simulated
      dependency processing across all attempts (fault/saturation delay
      included, scheduled backoff excluded).
    - ``retry``:   mean per-request sum of ``retry`` event delays — scheduled
      backoff sleeps between attempts.
    - ``other``:   ``total - service - retry`` — the residual: concurrency
      queue wait, circuit-open wait, timeout waits, and event-loop scheduling
      overhead.

    Returns zeroed fields when no request records are present.
    """
    reqs = requests(records)
    if not reqs:
        return {"total": 0.0, "service": 0.0, "retry": 0.0, "other": 0.0}

    service_by_request: dict[int, float] = {}
    retry_by_request: dict[int, float] = {}
    for row in downstreams(records):
        rid = row.get("request_id")
        if rid is not None:
            service_by_request[rid] = service_by_request.get(rid, 0.0) + float(
                row.get("latency") or 0.0
            )
    for row in events(records):
        if row.get("event") == "retry":
            rid = row.get("request_id")
            if rid is not None:
                retry_by_request[rid] = retry_by_request.get(rid, 0.0) + float(
                    row.get("delay") or 0.0
                )

    request_ids = [r["request_id"] for r in reqs]
    totals = [float(r["latency"]) for r in reqs if r.get("latency") is not None]
    services = [service_by_request.get(rid, 0.0) for rid in request_ids]
    retries = [retry_by_request.get(rid, 0.0) for rid in request_ids]
    others = [t - s - r for t, s, r in zip(totals, services, retries, strict=True)]

    def _mean(values: list[float]) -> float:
        return mean(values) if values else 0.0

    return {
        "total": _mean(totals),
        "service": _mean(services),
        "retry": _mean(retries),
        "other": _mean(others),
    }


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
