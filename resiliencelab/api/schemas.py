"""Pydantic request/response models for the ResilienceLab API."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


class ErrorCode(str, Enum):
    """Stable machine-readable error codes."""

    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
    request_id: str | None = None


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class PaginationMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    has_more: bool


# ---------------------------------------------------------------------------
# Health / Readiness
# ---------------------------------------------------------------------------


class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class DependencyHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: HealthStatus
    message: str = ""


class LivenessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: HealthStatus = HealthStatus.OK
    server_mode: bool
    version: str


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: HealthStatus
    server_mode: bool
    checks: dict[str, DependencyHealth] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Catalog responses (immutable reference data)
# ---------------------------------------------------------------------------


class BenchmarksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmarks: list[str]


class PoliciesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mechanisms: list[str]


class FaultModelsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_types: list[str]
    temporal_modes: list[str]


class WorkloadsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workload_types: list[str]


# ---------------------------------------------------------------------------
# Experiment request models
# ---------------------------------------------------------------------------


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any]
    idempotency_key: str | None = Field(default=None, max_length=256)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=2048)


# ---------------------------------------------------------------------------
# Experiment response models
# ---------------------------------------------------------------------------


class ExperimentSummary(BaseModel):
    """Compact experiment listing item — never includes full config or artifacts."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    status: str
    created_at: str | None = None


class ExperimentDetail(BaseModel):
    """Full experiment metadata — excludes raw config payload."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: int
    description: str
    status: str
    config_hash: str
    owner_id: str | None = None
    artifact_path: str | None = None
    error_message: str | None = None
    cancellation_reason: str | None = None
    cancelled_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ExperimentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiments: list[ExperimentSummary]
    pagination: PaginationMeta


class ExperimentCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    status: str


class ExperimentDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment: ExperimentDetail


# ---------------------------------------------------------------------------
# Run response models
# ---------------------------------------------------------------------------


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_index: int
    seed: int
    status: str
    artifact_path: str | None = None
    error_message: str | None = None
    cancellation_reason: str | None = None
    cancelled_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class RunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[RunSummary]


# ---------------------------------------------------------------------------
# Status response
# ---------------------------------------------------------------------------


class RunStatusItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str


class ExperimentStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    error: str | None = None
    cancellation_reason: str | None = None
    runs: list[RunStatusItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Cancel response
# ---------------------------------------------------------------------------


class CancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    message: str | None = None


# ---------------------------------------------------------------------------
# Run/requeue response
# ---------------------------------------------------------------------------


class RunExperimentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str


# ---------------------------------------------------------------------------
# Artifact responses
# ---------------------------------------------------------------------------


class ArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    config_hash: str
    raw_records_hash: str
    events_hash: str
    event_schema_version: str
    event_count: int
    cancelled: bool
    cancellation_reason: str | None = None
    requested_repetitions: int
    completed_repetitions: int
    files: dict[str, str]


class ArtifactFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    size_bytes: int | None = None


class ArtifactListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: ArtifactManifest
    files: list[ArtifactFile]


# ---------------------------------------------------------------------------
# Event responses
# ---------------------------------------------------------------------------


class EventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int | None = None
    event_type: str
    timestamp: float
    elapsed: float | None = None
    target_service: str | None = None
    metadata: dict[str, Any] | None = None


class EventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_schema_version: str
    count: int
    events: list[EventItem]


# ---------------------------------------------------------------------------
# Metrics / Analysis responses (local mode)
# ---------------------------------------------------------------------------


class MetricsPerRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics_per_run: list[dict[str, float]]


class TimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeline: list[list[dict[str, Any]]]


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: Any
