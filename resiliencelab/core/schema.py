"""Pydantic experiment schema — the declarative central abstraction."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resiliencelab.core.types import Duration
from resiliencelab.faults.model import FailureKind, LatencyDistribution, TemporalMode
from resiliencelab.resilience.backoff import BackoffKind
from resiliencelab.resilience.jitter import JitterKind


class WorkloadType(str, Enum):
    CLOSED_LOOP = "closed_loop"
    OPEN_LOOP = "open_loop"
    CONSTANT_RATE = "constant_rate"
    BURST = "burst"
    RAMP = "ramp"
    PERIODIC = "periodic"
    RANDOM = "random"


class ArrivalDistribution(str, Enum):
    POISSON = "poisson"
    CONSTANT = "constant"
    EXPONENTIAL = "exponential"


class SeedStrategy(str, Enum):
    DETERMINISTIC = "deterministic"
    RANDOM = "random"
    EXPLICIT = "explicit"


class SystemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replicas: int = Field(default=1, ge=1)
    workers_per_replica: int = Field(default=1, ge=1)


class WorkloadSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: WorkloadType = WorkloadType.CLOSED_LOOP
    clients: int = Field(default=10, ge=1)
    arrival_rate: float = Field(default=100.0, gt=0)
    duration: Duration = Field(default=60.0, gt=0)
    warmup: Duration = Field(default=0.0, ge=0)
    cooldown: Duration = Field(default=0.0, ge=0)
    distribution: ArrivalDistribution = ArrivalDistribution.POISSON
    payload_size: int = Field(default=64, ge=0)
    burstiness: float = Field(default=1.0, gt=0)
    endpoint_mix: list[str] = Field(default_factory=lambda: ["/"])


class FailureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = "dependency"
    type: FailureKind = FailureKind.HTTP_503
    mode: TemporalMode = TemporalMode.CONSTANT
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    duration: Duration = Field(default=0.0, ge=0)
    period: Duration = Field(default=0.0, ge=0)
    start: Duration = Field(default=0.0, ge=0)
    latency_distribution: LatencyDistribution = LatencyDistribution.UNIFORM
    latency_mean: Duration = Field(default=0.1, ge=0)
    latency_std: Duration = Field(default=0.05, ge=0)
    latency_min: Duration = Field(default=0.0, ge=0)
    latency_max: Duration = Field(default=0.2, ge=0)
    status_code: int | None = Field(default=None, ge=100, le=599)


class RetrySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_attempts: int = Field(default=3, ge=1)
    retryable_statuses: set[int] = Field(default_factory=lambda: {429, 500, 502, 503, 504})


class BackoffSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: BackoffKind = BackoffKind.EXPONENTIAL
    base: Duration = Field(default=0.1, ge=0)
    maximum: Duration = Field(default=5.0, ge=0)
    factor: float = Field(default=2.0, ge=1.0)
    jitter: JitterKind = JitterKind.NONE
    jitter_factor: float = Field(default=0.1, ge=0.0, le=1.0)


class CircuitBreakerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    threshold: int = Field(default=10, ge=1)
    recovery_window: Duration = Field(default=15.0, ge=0)
    half_open_probes: int = Field(default=1, ge=1)
    rolling_window: Duration | None = Field(default=None, gt=0)
    minimum_throughput: int = Field(default=1, ge=1)


class TimeoutSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connect: Duration | None = Field(default=None, gt=0)
    read: Duration | None = Field(default=None, gt=0)
    total: Duration | None = Field(default=None, gt=0)


class ConcurrencySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    limit: int = Field(default=50, ge=1)
    queue_limit: int | None = Field(default=0, ge=0)


class PolicySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retry: RetrySpec | None = None
    backoff: BackoffSpec = Field(default_factory=BackoffSpec)
    circuit_breaker: CircuitBreakerSpec | None = None
    timeout: TimeoutSpec | None = None
    concurrency: ConcurrencySpec | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> PolicySpec:
        if self.backoff.base > self.backoff.maximum:
            raise ValueError("backoff base cannot exceed maximum")
        if self.retry is not None and not self.retry.enabled:
            self.retry = None
        return self


class RepetitionsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=1, ge=1)
    seed_strategy: SeedStrategy = SeedStrategy.DETERMINISTIC
    base_seed: int = Field(default=0)


class EnvironmentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python_version: str | None = None
    cpu_limit: float | None = None
    memory_limit: str | None = None
    platform: str | None = None


class AnalysisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    availability_threshold: float = Field(default=0.9, gt=0, le=1)
    latency_tolerance: float = Field(default=0.25, gt=0)
    stability_window: Duration = Field(default=5.0, gt=0)
    confidence_level: float = Field(default=0.95, gt=0, lt=1)
    baseline_window: Duration | None = Field(default=None, gt=0)


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    description: str = ""
    system: SystemSpec = Field(default_factory=SystemSpec)
    workload: WorkloadSpec = Field(default_factory=WorkloadSpec)
    failure: list[FailureSpec] = Field(default_factory=list)
    policy: PolicySpec = Field(default_factory=PolicySpec)
    repetitions: RepetitionsSpec = Field(default_factory=RepetitionsSpec)
    environment: EnvironmentSpec = Field(default_factory=EnvironmentSpec)
    analysis: AnalysisSpec = Field(default_factory=AnalysisSpec)

    @model_validator(mode="after")
    def _check_warmup(self) -> ExperimentSpec:
        if self.workload.warmup >= self.workload.duration:
            raise ValueError("warmup must be shorter than total duration")
        return self
