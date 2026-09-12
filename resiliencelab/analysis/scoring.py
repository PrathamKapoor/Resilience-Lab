"""Composite resilience scoring with exposed, configurable weights."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_WEIGHTS = {
    "availability": 0.25,
    "tail_latency": 0.20,
    "recovery_time": 0.20,
    "amplification": 0.15,
    "error_rate": 0.10,
    "throughput": 0.10,
}


@dataclass
class ResilienceScore:
    score: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


def _normalize_tail_latency(p99: float, reference: float) -> float:
    if p99 <= 0 or reference <= 0:
        return 0.5
    ratio = p99 / reference
    return max(0.0, min(1.0, 1.0 - (ratio - 1.0)))


def _normalize_recovery(recovery_time: float, reference: float) -> float:
    if recovery_time == float("inf"):
        return 0.0
    if reference <= 0:
        return 1.0 if recovery_time <= 1e-6 else 0.5
    return max(0.0, min(1.0, 1.0 - recovery_time / reference))


def compute_score(
    *,
    availability: float,
    throughput: float,
    reference_throughput: float,
    p99: float,
    reference_p99: float,
    error_rate: float,
    amplification: float,
    recovery_time: float,
    reference_recovery_time: float,
    weights: dict[str, float] | None = None,
) -> ResilienceScore:
    w = weights or DEFAULT_WEIGHTS
    components = {
        "availability": max(0.0, min(1.0, availability)),
        "throughput": max(
            0.0, min(1.0, throughput / reference_throughput if reference_throughput > 0 else 0.0)
        ),
        "tail_latency": _normalize_tail_latency(p99, reference_p99),
        "error_rate": max(0.0, min(1.0, 1.0 - error_rate)),
        "amplification": max(0.0, min(1.0, 1.0 - (amplification - 1.0) / max(amplification, 1.0))),
        "recovery_time": _normalize_recovery(recovery_time, reference_recovery_time),
    }
    score = sum(components.get(k, 0.0) * weight for k, weight in w.items())
    return ResilienceScore(score=score, components=components, weights=w)
