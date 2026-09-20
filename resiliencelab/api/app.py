"""ResilienceLab REST API (FastAPI) — productionized control plane.

Architecture:
    API/CLI is the control plane. ExperimentRunner is the scientific execution engine.
    PostgreSQL is authoritative for lifecycle state. Redis is a queue only.
    Terminal states (COMPLETED/FAILED/CANCELLED) are immutable.
    CANCEL_REQUESTED ≠ CANCELLED. Cancelled ≠ failed ≠ completed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from sqlalchemy.orm import Session

from resiliencelab import __version__
from resiliencelab.api.auth import (
    Identity,
    get_identity,
    is_authenticated,
    validate_server_auth_configuration,
)
from resiliencelab.api.errors import install_error_handlers, new_request_id
from resiliencelab.api.schemas import (
    AnalysisResponse,
    ArtifactFile,
    ArtifactListResponse,
    ArtifactManifest,
    BenchmarksResponse,
    CancelRequest,
    CancelResponse,
    DependencyHealth,
    ErrorResponse,
    EventItem,
    EventListResponse,
    ExperimentCreate,
    ExperimentCreateResponse,
    ExperimentDetail,
    ExperimentDetailResponse,
    ExperimentListResponse,
    ExperimentStatusResponse,
    ExperimentSummary,
    FaultModelsResponse,
    HealthStatus,
    LivenessResponse,
    MetricsPerRunResponse,
    PaginationMeta,
    PoliciesResponse,
    ReadinessResponse,
    RunExperimentResponse,
    RunListResponse,
    RunStatusItem,
    RunSummary,
    TimelineResponse,
    WorkloadsResponse,
)
from resiliencelab.controlplane.database import init_session_factory
from resiliencelab.controlplane.queue import (
    enqueue_experiment,
    get_redis_client,
)
from resiliencelab.controlplane.repositories import (
    count_experiments as db_count_experiments,
)
from resiliencelab.controlplane.repositories import (
    create_experiment as db_create_experiment,
)
from resiliencelab.controlplane.repositories import (
    get_experiment as db_get_experiment,
)
from resiliencelab.controlplane.repositories import (
    get_runs as db_get_runs,
)
from resiliencelab.controlplane.repositories import (
    list_experiments as db_list_experiments,
)
from resiliencelab.controlplane.repositories import (
    request_cancel,
    update_experiment_status,
)
from resiliencelab.core.cancellation import CancellationToken
from resiliencelab.core.config import ConfigValidationError, dump_yaml, parse_experiment
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.provenance import hash_file
from resiliencelab.experiments.registry import ExperimentRegistry
from resiliencelab.experiments.report import automatic_analysis, build_report
from resiliencelab.experiments.result import ExperimentResult
from resiliencelab.experiments.runner import ExperimentRunner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
MAX_CONFIG_BODY_BYTES = 1_048_576  # 1 MB
MAX_EXPERIMENT_ID_LENGTH = 256
MAX_EXPERIMENT_REPETITIONS = 10_000

DASHBOARD_DIST = Path(__file__).resolve().parents[2] / "dashboard" / "dist"
DASHBOARD_BUILD_COMMAND = "npm --prefix dashboard run build"


def _is_server_mode() -> bool:
    return os.environ.get("RESILIENCELAB_SERVER_MODE", "").lower() in ("1", "true", "yes")


def _validate_experiment_id(experiment_id: str) -> None:
    if not experiment_id or len(experiment_id) > MAX_EXPERIMENT_ID_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Experiment ID must be 1-{MAX_EXPERIMENT_ID_LENGTH} characters",
        )
    if "/" in experiment_id or "\0" in experiment_id:
        raise HTTPException(status_code=422, detail="Experiment ID contains invalid characters")


def _dashboard_unavailable() -> PlainTextResponse:
    """Tell operators how to create the dashboard build required for serving."""
    return PlainTextResponse(
        f"Dashboard build is unavailable. Run: {DASHBOARD_BUILD_COMMAND}",
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


def _dashboard_asset(path: str) -> Path | None:
    """Return a built dashboard file only when its resolved path stays in the build."""
    dist = DASHBOARD_DIST.resolve()
    candidate = (dist / path).resolve()
    try:
        candidate.relative_to(dist)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _dashboard_cache_control(target: Path) -> str:
    """Classify cacheability from the resolved in-build target, never the request path."""
    relative_target = target.resolve().relative_to(DASHBOARD_DIST.resolve())
    if target.suffix.lower() == ".html":
        return "no-cache"
    if relative_target.parts and relative_target.parts[0] == "assets":
        return "public, max-age=31536000, immutable"
    return "no-cache"


def _dashboard_response(path: str = "") -> Response:
    """Serve one Vite asset or the SPA entry point for a dashboard client route."""
    index = DASHBOARD_DIST / "index.html"
    if not index.is_file():
        return _dashboard_unavailable()

    asset = _dashboard_asset(path) if path else None
    if asset is not None:
        return FileResponse(asset, headers={"Cache-Control": _dashboard_cache_control(asset)})

    return FileResponse(index, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------------------
# Local mode runtime (unchanged behavior)
# ---------------------------------------------------------------------------


class LocalRuntime:
    """In-memory runtime for local mode — preserves all existing behavior."""

    def __init__(self) -> None:
        self.registry = ExperimentRegistry()
        self.runner = ExperimentRunner()
        self.jobs: dict[str, dict[str, Any]] = {}
        self._cancellation_tokens: dict[str, CancellationToken] = {}

    async def submit(self, spec: ExperimentSpec) -> str:
        self.registry.register_spec(spec)
        job_id = spec.id
        self.jobs[job_id] = {"status": "running", "result": None, "error": None}
        token = CancellationToken()
        self._cancellation_tokens[job_id] = token
        asyncio.create_task(self.execute_and_store(spec, token))
        return job_id

    async def execute_and_store(
        self,
        spec: ExperimentSpec,
        token: CancellationToken | None = None,
    ) -> None:
        try:
            result = await self.runner.run_async(spec, cancellation_token=token)
        except Exception as exc:  # noqa: BLE001
            self.jobs[spec.id] = {"status": "failed", "result": None, "error": str(exc)}
            return
        if result.cancelled:
            self.jobs[spec.id] = {
                "status": "cancelled",
                "result": result,
                "error": result.cancellation_reason,
            }
        else:
            self.registry.register_result(result)
            self.jobs[spec.id] = {"status": "completed", "result": result, "error": None}

    def request_cancel(self, experiment_id: str, reason: str = "") -> tuple[bool, str]:
        job = self.jobs.get(experiment_id)
        if job is None:
            if self.registry.get_spec(experiment_id) is not None:
                return False, "not_started"
            return False, "not_found"
        if job["status"] in ("completed", "failed", "cancelled"):
            return False, f"already_{job['status']}"
        if job["status"] == "cancel_requested":
            return False, "already_cancel_requested"
        token = self._cancellation_tokens.get(experiment_id)
        if token is not None:
            token.request(reason=reason or "user requested")
        self.jobs[experiment_id]["status"] = "cancel_requested"
        return True, "cancel_requested"

    def job(self, experiment_id: str) -> dict[str, Any]:
        return self.jobs.get(experiment_id, {"status": "unknown", "result": None, "error": None})


def _result_or_404(runtime: LocalRuntime, experiment_id: str) -> ExperimentResult:
    result = runtime.registry.get_result(experiment_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no result for {experiment_id}")
    return result


# ---------------------------------------------------------------------------
# Server-mode DB helpers
# ---------------------------------------------------------------------------


def _db_session() -> Session:
    from resiliencelab.controlplane.database import create_session

    return create_session()


def _require_experiment(db: Session, experiment_id: str) -> Any:
    record = db_get_experiment(db, experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
    return record


def _check_ownership(record: Any, identity: Identity) -> None:
    """Authorize access: anonymous users can access everything; authenticated users
    can only access their own experiments unless they own nothing (admin fallback)."""
    if not is_authenticated(identity):
        return
    if record.owner_id is None:
        return
    if record.owner_id != identity.user_id:
        raise HTTPException(status_code=403, detail="access denied")


def _server_artifact_bases(db: Session, record: Any) -> list[Path]:
    """Return artifact bundles for completed runs in stable run-index order."""
    paths = [
        Path(str(run.artifact_path))
        for run in db_get_runs(db, record.experiment_id)
        if run.artifact_path
    ]
    if not paths and record.artifact_path:
        paths = [Path(str(record.artifact_path))]
    if not paths:
        raise HTTPException(status_code=404, detail="no artifacts available for this experiment")
    return paths


def _artifact_file_or_404(base: Path, relative_path: str) -> Path:
    target = base / relative_path
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"artifact file not found: {relative_path}")
    manifest_path = base / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="artifact manifest not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_hash = manifest.get("files", {}).get(relative_path)
    if expected_hash is None:
        raise HTTPException(status_code=409, detail="artifact file is not tracked by its manifest")
    if hash_file(str(target)) != expected_hash:
        raise HTTPException(status_code=409, detail="artifact integrity check failed")
    return target


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(runtime: LocalRuntime | None = None, server_mode: bool | None = None) -> FastAPI:
    use_server = server_mode if server_mode is not None else _is_server_mode()
    app = FastAPI(
        title="ResilienceLab API",
        version=__version__,
        description=(
            "Control-plane API for reproducible resilience experiments. "
            "The API manages lifecycle; ExperimentRunner executes scientific simulations."
        ),
    )

    install_error_handlers(app)

    # Request correlation middleware
    @app.middleware("http")
    async def add_request_id(request: Request, call_next: Any) -> Any:
        rid = request.headers.get("X-Request-ID", "") or new_request_id()
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    if use_server:
        validate_server_auth_configuration()
        try:
            init_session_factory()
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize database: {exc}") from exc

    v1 = APIRouter(prefix="/api/v1")

    # ---- Health / Readiness (no auth required) ----

    @v1.get("/health", response_model=LivenessResponse, tags=["health"])
    async def health() -> LivenessResponse:
        """Liveness: is the API process alive?"""
        return LivenessResponse(
            status=HealthStatus.OK,
            server_mode=use_server,
            version=__version__,
        )

    @v1.get("/ready", response_model=ReadinessResponse, tags=["health"])
    async def ready() -> ReadinessResponse:
        """Readiness: can this server-backed control plane operate?"""
        checks: dict[str, DependencyHealth] = {}
        overall = HealthStatus.OK
        if use_server:
            try:
                from resiliencelab.controlplane.database import create_session

                session = create_session()
                session.execute(__import__("sqlalchemy").text("SELECT 1"))
                session.close()
                checks["postgres"] = DependencyHealth(status=HealthStatus.OK)
            except Exception as exc:
                checks["postgres"] = DependencyHealth(
                    status=HealthStatus.DOWN, message=str(exc)[:200]
                )
                overall = HealthStatus.DOWN
            try:
                r = get_redis_client()
                r.ping()
                checks["redis"] = DependencyHealth(status=HealthStatus.OK)
            except Exception as exc:
                checks["redis"] = DependencyHealth(status=HealthStatus.DOWN, message=str(exc)[:200])
                overall = HealthStatus.DOWN
        return ReadinessResponse(status=overall, server_mode=use_server, checks=checks)

    # ---- Catalog endpoints (shared, immutable reference data) ----

    @v1.get("/benchmarks", response_model=BenchmarksResponse, tags=["catalog"])
    async def list_benchmarks() -> BenchmarksResponse:
        from resiliencelab.experiments.benchmarks import list_standard_benchmarks

        return BenchmarksResponse(benchmarks=list_standard_benchmarks())

    @v1.get("/policies", response_model=PoliciesResponse, tags=["catalog"])
    async def list_policies() -> PoliciesResponse:
        return PoliciesResponse(
            mechanisms=[
                "retry",
                "backoff",
                "jitter",
                "circuit_breaker",
                "timeout",
                "concurrency",
            ]
        )

    @v1.get("/fault-models", response_model=FaultModelsResponse, tags=["catalog"])
    async def list_fault_models() -> FaultModelsResponse:
        from resiliencelab.faults.model import FailureKind, TemporalMode

        return FaultModelsResponse(
            failure_types=[k.value for k in FailureKind],
            temporal_modes=[m.value for m in TemporalMode],
        )

    @v1.get("/workloads", response_model=WorkloadsResponse, tags=["catalog"])
    async def list_workloads() -> WorkloadsResponse:
        from resiliencelab.core.schema import WorkloadType

        return WorkloadsResponse(workload_types=[w.value for w in WorkloadType])

    # ---- Mode-specific routes ----

    if use_server:
        _register_server_routes(v1)
    else:
        _register_local_routes(v1, runtime)

    app.include_router(v1)

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard() -> Response:
        return _dashboard_response()

    @app.get("/dashboard/{path:path}", include_in_schema=False)
    async def dashboard_path(path: str) -> Response:
        return _dashboard_response(path)

    return app


# ---------------------------------------------------------------------------
# Server mode routes
# ---------------------------------------------------------------------------


def _register_server_routes(v1: APIRouter) -> None:
    @v1.post(
        "/experiments",
        status_code=201,
        response_model=ExperimentCreateResponse,
        responses={
            409: {"model": ErrorResponse, "description": "Idempotent: experiment already exists"},
            422: {"model": ErrorResponse, "description": "Invalid experiment configuration"},
        },
        tags=["experiments"],
    )
    async def create_experiment(
        payload: ExperimentCreate, identity: Identity = Depends(get_identity)
    ) -> ExperimentCreateResponse:
        try:
            spec = parse_experiment(payload.config)
        except (ConfigValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        _validate_experiment_id(spec.id)

        if spec.repetitions.count > MAX_EXPERIMENT_REPETITIONS:
            raise HTTPException(
                status_code=422,
                detail=f"Repetitions count {spec.repetitions.count} exceeds maximum {MAX_EXPERIMENT_REPETITIONS}",
            )

        def _create(db: Session) -> ExperimentCreateResponse:
            existing = db_get_experiment(db, spec.id)
            if existing and existing.status in ("CREATED", "QUEUED"):
                return ExperimentCreateResponse(id=spec.id, name=spec.name, status="created")
            if existing and existing.status in ("COMPLETED", "FAILED", "CANCELLED"):
                raise HTTPException(
                    status_code=409,
                    detail=f"experiment {spec.id} already exists in terminal state {existing.status}",
                )

            config_yaml = dump_yaml(spec)
            from resiliencelab.experiments.provenance import hash_config

            config_hash = hash_config(spec)
            owner_id = identity.user_id if is_authenticated(identity) else None
            db_create_experiment(
                db,
                experiment_id=spec.id,
                name=spec.name,
                version=spec.version,
                description=spec.description,
                config_yaml=config_yaml,
                config_hash=config_hash,
                status="CREATED",
                owner_id=owner_id,
            )
            r = get_redis_client()
            enqueue_experiment(r, spec.id, config_yaml, config_hash, spec.repetitions.count)
            update_experiment_status(db, spec.id, "QUEUED")
            return ExperimentCreateResponse(id=spec.id, name=spec.name, status="queued")

        db = _db_session()
        try:
            result = _create(db)
            db.commit()
            return result
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @v1.get(
        "/experiments",
        response_model=ExperimentListResponse,
        responses={422: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def list_experiments(
        status: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        identity: Identity = Depends(get_identity),
    ) -> ExperimentListResponse:
        db = _db_session()
        try:
            owner = identity.user_id if is_authenticated(identity) else None
            total = db_count_experiments(db, status=status, owner_id=owner)
            experiments = db_list_experiments(
                db, status=status, owner_id=owner, offset=offset, limit=limit
            )
            has_more = (offset + limit) < total
            return ExperimentListResponse(
                experiments=[
                    ExperimentSummary(
                        id=exp.experiment_id,
                        name=exp.name,
                        status=exp.status,
                        created_at=exp.created_at.isoformat() if exp.created_at else None,
                    )
                    for exp in experiments
                ],
                pagination=PaginationMeta(
                    total=total, offset=offset, limit=limit, has_more=has_more
                ),
            )
        finally:
            db.close()

    @v1.get(
        "/experiments/{experiment_id}",
        response_model=ExperimentDetailResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def get_experiment(
        experiment_id: str, identity: Identity = Depends(get_identity)
    ) -> ExperimentDetailResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
            return ExperimentDetailResponse(
                experiment=ExperimentDetail(
                    id=record.experiment_id,
                    name=record.name,
                    version=record.version,
                    description=record.description,
                    status=record.status,
                    config_hash=record.config_hash,
                    owner_id=record.owner_id,
                    artifact_path=record.artifact_path,
                    error_message=record.error_message,
                    cancellation_reason=record.cancellation_reason,
                    cancelled_at=record.cancelled_at.isoformat() if record.cancelled_at else None,
                    created_at=record.created_at.isoformat() if record.created_at else None,
                    updated_at=record.updated_at.isoformat() if record.updated_at else None,
                )
            )
        finally:
            db.close()

    @v1.get(
        "/experiments/{experiment_id}/runs",
        response_model=RunListResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["runs"],
    )
    async def list_runs(
        experiment_id: str, identity: Identity = Depends(get_identity)
    ) -> RunListResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
            runs = db_get_runs(db, experiment_id)
            return RunListResponse(
                runs=[
                    RunSummary(
                        run_id=run.run_id,
                        run_index=run.run_index,
                        seed=run.seed,
                        status=run.status,
                        artifact_path=run.artifact_path,
                        error_message=run.error_message,
                        cancellation_reason=run.cancellation_reason,
                        cancelled_at=run.cancelled_at.isoformat() if run.cancelled_at else None,
                        started_at=run.started_at.isoformat() if run.started_at else None,
                        completed_at=run.completed_at.isoformat() if run.completed_at else None,
                    )
                    for run in runs
                ]
            )
        finally:
            db.close()

    @v1.post(
        "/experiments/{experiment_id}/run",
        response_model=RunExperimentResponse,
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse, "description": "Experiment in wrong state"},
        },
        tags=["experiments"],
    )
    async def run_experiment(
        experiment_id: str, identity: Identity = Depends(get_identity)
    ) -> RunExperimentResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
            if record.status not in ("CREATED", "COMPLETED", "CANCELLED", "FAILED"):
                raise HTTPException(
                    status_code=409, detail=f"experiment is {record.status}, cannot run"
                )
            import yaml

            spec_data = yaml.safe_load(record.config_yaml)
            spec = parse_experiment(spec_data)
            config_yaml = str(record.config_yaml)
            config_hash = str(record.config_hash)
            r = get_redis_client()
            enqueue_experiment(r, experiment_id, config_yaml, config_hash, spec.repetitions.count)
            update_experiment_status(db, experiment_id, "QUEUED")
            db.commit()
            return RunExperimentResponse(id=experiment_id, status="queued")
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @v1.post(
        "/experiments/{experiment_id}/cancel",
        response_model=CancelResponse,
        responses={
            404: {"model": ErrorResponse},
        },
        tags=["experiments"],
    )
    async def cancel_experiment(
        experiment_id: str,
        payload: CancelRequest | None = None,
        identity: Identity = Depends(get_identity),
    ) -> CancelResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = db_get_experiment(db, experiment_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
            _check_ownership(record, identity)
            reason = payload.reason if payload else ""
            success, status_msg = request_cancel(db, experiment_id, reason=reason)
            if not success:
                if status_msg == "not_found":
                    raise HTTPException(
                        status_code=404, detail=f"unknown experiment {experiment_id}"
                    )
                return CancelResponse(
                    id=experiment_id,
                    status=status_msg,
                    message=f"experiment is already {status_msg}",
                )
            db.commit()
            return CancelResponse(id=experiment_id, status=status_msg)
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @v1.get(
        "/experiments/{experiment_id}/status",
        response_model=ExperimentStatusResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_status(
        experiment_id: str, identity: Identity = Depends(get_identity)
    ) -> ExperimentStatusResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
            runs = db_get_runs(db, experiment_id)
            return ExperimentStatusResponse(
                id=experiment_id,
                status=record.status,
                error=record.error_message,
                cancellation_reason=record.cancellation_reason,
                runs=[RunStatusItem(run_id=run.run_id, status=run.status) for run in runs],
            )
        finally:
            db.close()

    @v1.get(
        "/experiments/{experiment_id}/artifacts",
        response_model=ArtifactListResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["artifacts"],
    )
    async def experiment_artifacts(
        experiment_id: str, identity: Identity = Depends(get_identity)
    ) -> ArtifactListResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
            if record.artifact_path is None:
                raise HTTPException(
                    status_code=404, detail="no artifacts available for this experiment"
                )

            import json
            from pathlib import Path

            base = Path(record.artifact_path)
            manifest_path = base / "manifest.json"
            if not manifest_path.exists():
                raise HTTPException(status_code=404, detail="artifact manifest not found on disk")
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = ArtifactManifest(**manifest_data)

            files: list[ArtifactFile] = []
            for fname, sha256 in manifest.files.items():
                fpath = base / fname
                size = fpath.stat().st_size if fpath.exists() else None
                files.append(ArtifactFile(path=fname, sha256=sha256, size_bytes=size))

            return ArtifactListResponse(manifest=manifest, files=files)
        finally:
            db.close()

    @v1.get(
        "/experiments/{experiment_id}/events",
        response_model=EventListResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["events"],
    )
    async def experiment_events(
        experiment_id: str,
        event_type: str | None = None,
        service: str | None = None,
        identity: Identity = Depends(get_identity),
    ) -> EventListResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
        finally:
            db.close()

        from resiliencelab.controlplane.models import ExperimentEventRecord

        db = _db_session()
        try:
            from sqlalchemy import select as sa_select

            q = sa_select(ExperimentEventRecord).where(
                ExperimentEventRecord.experiment_id == experiment_id
            )
            if event_type:
                q = q.where(ExperimentEventRecord.event_type == event_type)
            if service:
                q = q.where(ExperimentEventRecord.target_service == service)
            q = q.order_by(ExperimentEventRecord.timestamp).limit(1000)
            rows = list(db.execute(q).scalars().all())
            return EventListResponse(
                event_schema_version="1",
                count=len(rows),
                events=[
                    EventItem(
                        sequence=None,
                        event_type=row.event_type,
                        timestamp=row.timestamp,
                        elapsed=row.elapsed,
                        target_service=row.target_service,
                        metadata=row.metadata_json,
                    )
                    for row in rows
                ],
            )
        finally:
            db.close()

    @v1.get(
        "/experiments/{experiment_id}/metrics",
        response_model=MetricsPerRunResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_metrics(
        experiment_id: str, identity: Identity = Depends(get_identity)
    ) -> MetricsPerRunResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
            metrics: list[dict[str, float]] = []
            for base in _server_artifact_bases(db, record):
                summary = json.loads(_artifact_file_or_404(base, "experiment.json").read_text())
                metrics.extend(summary["metrics_per_run"])
            return MetricsPerRunResponse(metrics_per_run=metrics)
        finally:
            db.close()

    @v1.get(
        "/experiments/{experiment_id}/timeline",
        response_model=TimelineResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_timeline(
        experiment_id: str, identity: Identity = Depends(get_identity)
    ) -> TimelineResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
            timelines = [
                json.loads(_artifact_file_or_404(base, "analysis/timeline-0.json").read_text())
                for base in _server_artifact_bases(db, record)
            ]
            return TimelineResponse(timeline=timelines)
        finally:
            db.close()

    @v1.get(
        "/experiments/{experiment_id}/report",
        response_class=PlainTextResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_report(
        experiment_id: str, identity: Identity = Depends(get_identity)
    ) -> str:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
            reports = [
                _artifact_file_or_404(base, "report/report.md").read_text()
                for base in _server_artifact_bases(db, record)
            ]
            return "\n\n".join(reports)
        finally:
            db.close()

    @v1.get(
        "/experiments/{experiment_id}/analysis",
        response_model=AnalysisResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_analysis(
        experiment_id: str, identity: Identity = Depends(get_identity)
    ) -> AnalysisResponse:
        _validate_experiment_id(experiment_id)
        db = _db_session()
        try:
            record = _require_experiment(db, experiment_id)
            _check_ownership(record, identity)
            analyses = [
                json.loads(_artifact_file_or_404(base, "analysis/statistics.json").read_text())
                for base in _server_artifact_bases(db, record)
            ]
            analysis: Any = analyses[0] if len(analyses) == 1 else {"runs": analyses}
            return AnalysisResponse(analysis=analysis)
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Local mode routes
# ---------------------------------------------------------------------------


def _register_local_routes(v1: APIRouter, runtime: LocalRuntime | None) -> None:
    runtime = runtime or LocalRuntime()

    @v1.post(
        "/experiments",
        status_code=201,
        response_model=ExperimentCreateResponse,
        responses={422: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def create_experiment(
        payload: ExperimentCreate,
        identity: Identity = Depends(get_identity),
    ) -> ExperimentCreateResponse:
        try:
            spec = parse_experiment(payload.config)
        except (ConfigValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _validate_experiment_id(spec.id)
        runtime.registry.register_spec(spec)
        return ExperimentCreateResponse(id=spec.id, name=spec.name, status="created")

    @v1.get("/experiments", response_model=ExperimentListResponse, tags=["experiments"])
    async def list_experiments(
        status: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        identity: Identity = Depends(get_identity),
    ) -> ExperimentListResponse:
        ids = runtime.registry.spec_ids()
        total = len(ids)
        page = ids[offset : offset + limit]
        has_more = (offset + limit) < total
        return ExperimentListResponse(
            experiments=[ExperimentSummary(id=i, name=i, status="created") for i in page],
            pagination=PaginationMeta(total=total, offset=offset, limit=limit, has_more=has_more),
        )

    @v1.get(
        "/experiments/{experiment_id}",
        response_model=ExperimentDetailResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def get_experiment(
        experiment_id: str,
        identity: Identity = Depends(get_identity),
    ) -> ExperimentDetailResponse:
        _validate_experiment_id(experiment_id)
        spec = runtime.registry.get_spec(experiment_id)
        result = runtime.registry.get_result(experiment_id)
        if spec is None and result is not None:
            spec = result.experiment
        if spec is None:
            raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
        return ExperimentDetailResponse(
            experiment=ExperimentDetail(
                id=spec.id,
                name=spec.name,
                version=spec.version,
                description=spec.description,
                status="created",
                config_hash="",
                owner_id=None,
            )
        )

    @v1.post(
        "/experiments/{experiment_id}/run",
        response_model=RunExperimentResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def run_experiment(
        experiment_id: str,
        background_tasks: BackgroundTasks,
        identity: Identity = Depends(get_identity),
    ) -> RunExperimentResponse:
        _validate_experiment_id(experiment_id)
        spec = runtime.registry.get_spec(experiment_id)
        result = runtime.registry.get_result(experiment_id)
        if spec is None and result is not None:
            spec = result.experiment
        if spec is None:
            raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
        runtime.registry.register_spec(spec)
        runtime.jobs[experiment_id] = {"status": "running", "result": None, "error": None}
        token = CancellationToken()
        runtime._cancellation_tokens[experiment_id] = token
        background_tasks.add_task(runtime.execute_and_store, spec, token)
        return RunExperimentResponse(id=experiment_id, status="running")

    @v1.post(
        "/experiments/{experiment_id}/cancel",
        response_model=CancelResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def cancel_experiment(
        experiment_id: str,
        payload: CancelRequest | None = None,
        identity: Identity = Depends(get_identity),
    ) -> CancelResponse:
        _validate_experiment_id(experiment_id)
        reason = payload.reason if payload else ""
        success, status_msg = runtime.request_cancel(experiment_id, reason=reason)
        if not success:
            if status_msg == "not_found":
                raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
            return CancelResponse(
                id=experiment_id,
                status=status_msg,
                message=f"experiment is already {status_msg}",
            )
        return CancelResponse(id=experiment_id, status=status_msg)

    @v1.get(
        "/experiments/{experiment_id}/status",
        response_model=ExperimentStatusResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_status(
        experiment_id: str,
        identity: Identity = Depends(get_identity),
    ) -> ExperimentStatusResponse:
        _validate_experiment_id(experiment_id)
        job = runtime.job(experiment_id)
        return ExperimentStatusResponse(
            id=experiment_id,
            status=job["status"],
            error=job["error"],
        )

    @v1.get(
        "/experiments/{experiment_id}/metrics",
        response_model=MetricsPerRunResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_metrics(
        experiment_id: str,
        identity: Identity = Depends(get_identity),
    ) -> MetricsPerRunResponse:
        _validate_experiment_id(experiment_id)
        result = _result_or_404(runtime, experiment_id)
        return MetricsPerRunResponse(metrics_per_run=result.metrics_per_run())

    @v1.get(
        "/experiments/{experiment_id}/timeline",
        response_model=TimelineResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_timeline(
        experiment_id: str,
        identity: Identity = Depends(get_identity),
    ) -> TimelineResponse:
        _validate_experiment_id(experiment_id)
        result = _result_or_404(runtime, experiment_id)
        return TimelineResponse(timeline=[run.timeline for run in result.runs])

    @v1.get(
        "/experiments/{experiment_id}/events",
        response_model=EventListResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["events"],
    )
    async def experiment_events(
        experiment_id: str,
        event_type: str | None = None,
        service: str | None = None,
        request_id: int | None = None,
        identity: Identity = Depends(get_identity),
    ) -> EventListResponse:
        _validate_experiment_id(experiment_id)
        from resiliencelab.analysis.events import filter_events

        result = _result_or_404(runtime, experiment_id)
        events = filter_events(
            result.run_events(),
            event_type=event_type,
            service=service,
            request_id=request_id,
        )
        return EventListResponse(
            event_schema_version="1",
            count=len(events),
            events=[
                EventItem(
                    sequence=e.sequence if hasattr(e, "sequence") else None,
                    event_type=e.event_type,
                    timestamp=e.timestamp,
                    elapsed=e.elapsed if hasattr(e, "elapsed") else None,
                    target_service=e.target_service if hasattr(e, "target_service") else None,
                    metadata=e.metadata if hasattr(e, "metadata") else None,
                )
                for e in events
            ],
        )

    @v1.get(
        "/experiments/{experiment_id}/report",
        response_class=PlainTextResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_report(
        experiment_id: str,
        identity: Identity = Depends(get_identity),
    ) -> str:
        _validate_experiment_id(experiment_id)
        result = _result_or_404(runtime, experiment_id)
        return build_report(result)

    @v1.get(
        "/experiments/{experiment_id}/analysis",
        response_model=AnalysisResponse,
        responses={404: {"model": ErrorResponse}},
        tags=["experiments"],
    )
    async def experiment_analysis(
        experiment_id: str,
        identity: Identity = Depends(get_identity),
    ) -> AnalysisResponse:
        _validate_experiment_id(experiment_id)
        result = _result_or_404(runtime, experiment_id)
        return AnalysisResponse(analysis=automatic_analysis(result))

    @v1.get("/benchmarks", response_model=BenchmarksResponse, tags=["catalog"])
    async def list_benchmarks() -> BenchmarksResponse:
        from resiliencelab.experiments.benchmarks import list_standard_benchmarks

        return BenchmarksResponse(benchmarks=list_standard_benchmarks())

    @v1.get("/policies", response_model=PoliciesResponse, tags=["catalog"])
    async def list_policies() -> PoliciesResponse:
        return PoliciesResponse(
            mechanisms=[
                "retry",
                "backoff",
                "jitter",
                "circuit_breaker",
                "timeout",
                "concurrency",
            ]
        )

    @v1.get("/fault-models", response_model=FaultModelsResponse, tags=["catalog"])
    async def list_fault_models() -> FaultModelsResponse:
        from resiliencelab.faults.model import FailureKind, TemporalMode

        return FaultModelsResponse(
            failure_types=[k.value for k in FailureKind],
            temporal_modes=[m.value for m in TemporalMode],
        )

    @v1.get("/workloads", response_model=WorkloadsResponse, tags=["catalog"])
    async def list_workloads() -> WorkloadsResponse:
        from resiliencelab.core.schema import WorkloadType

        return WorkloadsResponse(workload_types=[w.value for w in WorkloadType])


app = create_app()
