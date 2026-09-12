"""Build a correlated per-bucket timeline from raw observation records."""

from __future__ import annotations

from resiliencelab.metrics.collector import Record
from resiliencelab.metrics.transforms import downstreams, events, requests


def _pct(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    index = p * (n - 1)
    lower = int(index)
    upper = min(lower + 1, n - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (index - lower)


def build_timeline(records: list[Record], bucket: float = 1.0) -> list[Record]:
    reqs = requests(records)
    ds = downstreams(records)
    evs = events(records)
    if not reqs:
        return []
    t0 = min(r["t"] for r in reqs)
    t1 = max(r["t"] for r in reqs)
    n = int((t1 - t0) / bucket) + 1

    latencies: list[list[float]] = [[] for _ in range(n)]
    counts = [0] * n
    errors = [0] * n
    timeouts = [0] * n
    retries = [0] * n
    down_counts = [0] * n
    down_failures = [0] * n
    down_latencies: list[list[float]] = [[] for _ in range(n)]

    for r in reqs:
        idx = min(int((r["t"] - t0) / bucket), n - 1)
        counts[idx] += 1
        if not r.get("success"):
            errors[idx] += 1
        if r.get("timeout"):
            timeouts[idx] += 1
        if r.get("latency") is not None:
            latencies[idx].append(r["latency"])

    for d in ds:
        idx = min(int((d["t"] - t0) / bucket), n - 1)
        down_counts[idx] += 1
        if not d.get("success"):
            down_failures[idx] += 1
        if d.get("latency") is not None:
            down_latencies[idx].append(d["latency"])
        if d.get("attempt", 1) and d["attempt"] > 1:
            retries[idx] += 1

    circuit_by_bucket: dict[int, str] = {}
    for e in evs:
        if e.get("event") in ("circuit_open", "circuit_close", "circuit_half_open"):
            idx = min(int((e["t"] - t0) / bucket), n - 1)
            circuit_by_bucket[idx] = e["event"].replace("circuit_", "") + "_"

    timeline: list[Record] = []
    for i in range(n):
        t = t0 + i * bucket + bucket / 2
        request_count = counts[i]
        timeline.append(
            {
                "t": t,
                "rps": request_count / bucket,
                "errors_per_sec": errors[i] / bucket,
                "availability": (request_count - errors[i]) / request_count
                if request_count
                else 1.0,
                "p95": _pct(sorted(latencies[i]), 0.95),
                "p99": _pct(sorted(latencies[i]), 0.99),
                "retries": retries[i],
                "timeouts": timeouts[i],
                "downstream_rps": down_counts[i] / bucket,
                "downstream_failures": down_failures[i],
                "amplification": down_counts[i] / request_count if request_count else 0.0,
                "circuit_state": circuit_by_bucket.get(i),
            }
        )
    return timeline
