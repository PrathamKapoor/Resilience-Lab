"""Fault injection type enumerations and data model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from numpy.random import Generator


class FailureKind(str, Enum):
    HTTP_500 = "http_500"
    HTTP_502 = "http_502"
    HTTP_503 = "http_503"
    HTTP_429 = "http_429"
    HTTP_ERROR = "http_error"
    CONNECTION_RESET = "connection_reset"
    CONNECTION_REFUSED = "connection_refused"
    TIMEOUT = "timeout"
    LATENCY = "latency"
    LATENCY_SPIKE = "latency_spike"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    SATURATION = "saturation"
    PARTIAL = "partial"


HTTP_STATUS_BY_KIND: dict[FailureKind, int] = {
    FailureKind.HTTP_500: 500,
    FailureKind.HTTP_502: 502,
    FailureKind.HTTP_503: 503,
    FailureKind.HTTP_429: 429,
    FailureKind.HTTP_ERROR: 500,
    FailureKind.DEPENDENCY_UNAVAILABLE: 503,
}


class TemporalMode(str, Enum):
    CONSTANT = "constant"
    RANDOM = "random"
    BURST = "burst"
    PERIODIC = "periodic"
    STEP = "step"
    RAMP = "ramp"


class LatencyDistribution(str, Enum):
    CONSTANT = "constant"
    UNIFORM = "uniform"
    NORMAL = "normal"
    LOGNORMAL = "lognormal"
    PARETO = "pareto"


@dataclass(frozen=True)
class FaultSpec:
    kind: FailureKind = FailureKind.HTTP_503
    mode: TemporalMode = TemporalMode.CONSTANT
    probability: float = 1.0
    start: float = 0.0
    duration: float = 0.0
    period: float = 0.0
    latency_distribution: LatencyDistribution = LatencyDistribution.UNIFORM
    latency_mean: float = 0.1
    latency_std: float = 0.05
    latency_min: float = 0.0
    latency_max: float = 0.2
    status_code: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("fault probability must be within [0, 1]")
        if self.duration < 0:
            raise ValueError("fault duration must be >= 0")


@dataclass(frozen=True)
class FaultEvent:
    kind: FailureKind
    latency: float = 0.0
    status_code: int | None = None


@dataclass
class FaultInjector:
    spec: FaultSpec

    def is_active(self, now: float) -> bool:
        spec = self.spec
        t = now - spec.start
        if spec.mode is TemporalMode.CONSTANT or spec.mode is TemporalMode.RANDOM:
            return t >= 0
        if spec.mode is TemporalMode.STEP:
            if spec.duration <= 0:
                return t >= 0
            return 0 <= t < spec.duration
        if spec.mode is TemporalMode.BURST or spec.mode is TemporalMode.PERIODIC:
            if t < 0:
                return False
            if spec.period <= 0:
                return spec.duration <= 0 or t < spec.duration
            return (t % spec.period) < spec.duration
        if spec.mode is TemporalMode.RAMP:
            return t >= 0
        return False

    def failure_probability(self, now: float) -> float:
        spec = self.spec
        if spec.mode is TemporalMode.RAMP:
            t = now - spec.start
            if t <= 0:
                return 0.0
            if spec.duration > 0 and t < spec.duration:
                return spec.probability * (t / spec.duration)
            return spec.probability
        return spec.probability

    def sample_latency(self, rng: Generator) -> float:
        spec = self.spec
        if spec.latency_distribution is LatencyDistribution.CONSTANT:
            return spec.latency_mean
        if spec.latency_distribution is LatencyDistribution.UNIFORM:
            return rng.uniform(spec.latency_min, spec.latency_max)
        if spec.latency_distribution is LatencyDistribution.NORMAL:
            return max(0.0, rng.normal(spec.latency_mean, spec.latency_std))
        if spec.latency_distribution is LatencyDistribution.LOGNORMAL:
            import math

            mu = math.log(max(spec.latency_mean, 1e-9))
            return float(rng.lognormal(mean=mu, sigma=spec.latency_std))
        if spec.latency_distribution is LatencyDistribution.PARETO:
            return float(rng.pareto(2.0)) + spec.latency_min
        return 0.0

    def evaluate(self, now: float, rng: Generator) -> FaultEvent | None:
        if not self.is_active(now):
            return None
        if rng.random() > self.failure_probability(now):
            return None
        latency = 0.0
        if self.spec.kind in (FailureKind.LATENCY, FailureKind.LATENCY_SPIKE):
            latency = self.sample_latency(rng)
        status = self.spec.status_code or HTTP_STATUS_BY_KIND.get(self.spec.kind)
        return FaultEvent(kind=self.spec.kind, latency=latency, status_code=status)
