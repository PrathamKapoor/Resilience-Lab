"""ResilienceLab REST API (FastAPI) — persistent control plane."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from resiliencelab.controlplane.database import init_session_factory
from resiliencelab.controlplane.queue import (
    enqueue_experiment,
    get_redis_client,
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
from resiliencelab.experiments.registry import ExperimentRegistry
from resiliencelab.experiments.report import automatic_analysis, build_report
from resiliencelab.experiments.result import ExperimentResult
from resiliencelab.experiments.runner import ExperimentRunner


class ExperimentCreate(BaseModel):
    config: dict[str, Any]


class CancelRequest(BaseModel):
    reason: str = ""


def _is_server_mode() -> bool:
    return os.environ.get("RESILIENCELAB_SERVER_MODE", "").lower() in ("1", "true", "yes")


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
        """Request cancellation of a running experiment.

        Returns (success, status_message).
        """
        job = self.jobs.get(experiment_id)
        if job is None:
            # Check if experiment exists in registry but hasn't been run
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


def create_app(runtime: LocalRuntime | None = None, server_mode: bool | None = None) -> FastAPI:
    use_server = server_mode if server_mode is not None else _is_server_mode()
    app = FastAPI(title="ResilienceLab API", version="0.3.0")

    if use_server:
        try:
            init_session_factory()
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize database: {exc}") from exc

    v1 = APIRouter(prefix="/api/v1")

    @v1.get("/health")
    async def health() -> dict[str, Any]:
        checks: dict[str, str] = {}
        if use_server:
            try:
                from resiliencelab.controlplane.database import create_session

                session = create_session()
                session.execute(__import__("sqlalchemy").text("SELECT 1"))
                session.close()
                checks["postgres"] = "ok"
            except Exception:
                checks["postgres"] = "error"
            try:
                r = get_redis_client()
                r.ping()
                checks["redis"] = "ok"
            except Exception:
                checks["redis"] = "error"
        return {"status": "ok", "server_mode": use_server, "checks": checks}

    if use_server:
        _register_server_routes(v1)
    else:
        _register_local_routes(v1, runtime)

    app.include_router(v1)
    return app


def _register_server_routes(v1: APIRouter) -> None:
    @v1.post("/experiments", status_code=201)
    async def create_experiment(payload: ExperimentCreate) -> dict[str, Any]:
        try:
            spec = parse_experiment(payload.config)
        except (ConfigValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        def _create(db: Session) -> dict[str, Any]:
            existing = db_get_experiment(db, spec.id)
            if existing and existing.status in ("CREATED", "QUEUED"):
                return {"id": spec.id, "name": spec.name, "status": "created"}
            config_yaml = dump_yaml(spec)
            from resiliencelab.experiments.provenance import hash_config

            config_hash = hash_config(spec)
            db_create_experiment(
                db,
                experiment_id=spec.id,
                name=spec.name,
                version=spec.version,
                description=spec.description,
                config_yaml=config_yaml,
                config_hash=config_hash,
                status="CREATED",
            )
            r = get_redis_client()
            enqueue_experiment(r, spec.id, config_yaml, config_hash, spec.repetitions.count)
            update_experiment_status(db, spec.id, "QUEUED")
            return {"id": spec.id, "name": spec.name, "status": "queued"}

        from resiliencelab.controlplane.database import create_session

        db = create_session()
        try:
            result = _create(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @v1.get("/experiments")
    async def list_experiments(
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        from resiliencelab.controlplane.database import create_session

        db = create_session()
        try:
            experiments = db_list_experiments(db, status=status, offset=offset, limit=limit)
            return {
                "experiments": [
                    {
                        "id": exp.experiment_id,
                        "name": exp.name,
                        "status": exp.status,
                        "created_at": exp.created_at.isoformat() if exp.created_at else None,
                    }
                    for exp in experiments
                ]
            }
        finally:
            db.close()

    @v1.get("/experiments/{experiment_id}")
    async def get_experiment(experiment_id: str) -> dict[str, Any]:
        from resiliencelab.controlplane.database import create_session

        db = create_session()
        try:
            record = db_get_experiment(db, experiment_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
            return {
                "experiment": {
                    "id": record.experiment_id,
                    "name": record.name,
                    "version": record.version,
                    "description": record.description,
                    "status": record.status,
                    "config_hash": record.config_hash,
                    "artifact_path": record.artifact_path,
                    "error_message": record.error_message,
                    "cancellation_reason": record.cancellation_reason,
                    "cancelled_at": record.cancelled_at.isoformat()
                    if record.cancelled_at
                    else None,
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                    "updated_at": record.updated_at.isoformat() if record.updated_at else None,
                }
            }
        finally:
            db.close()

    @v1.get("/experiments/{experiment_id}/runs")
    async def list_runs(experiment_id: str) -> dict[str, Any]:
        from resiliencelab.controlplane.database import create_session

        db = create_session()
        try:
            runs = db_get_runs(db, experiment_id)
            return {
                "runs": [
                    {
                        "run_id": run.run_id,
                        "run_index": run.run_index,
                        "seed": run.seed,
                        "status": run.status,
                        "artifact_path": run.artifact_path,
                        "error_message": run.error_message,
                        "cancellation_reason": run.cancellation_reason,
                        "cancelled_at": run.cancelled_at.isoformat() if run.cancelled_at else None,
                        "started_at": run.started_at.isoformat() if run.started_at else None,
                        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    }
                    for run in runs
                ]
            }
        finally:
            db.close()

    @v1.post("/experiments/{experiment_id}/run")
    async def run_experiment(experiment_id: str) -> dict[str, Any]:
        from resiliencelab.controlplane.database import create_session

        db = create_session()
        try:
            record = db_get_experiment(db, experiment_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
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
            return {"id": experiment_id, "status": "queued"}
        except HTTPException:
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @v1.post("/experiments/{experiment_id}/cancel")
    async def cancel_experiment(
        experiment_id: str,
        payload: CancelRequest | None = None,
    ) -> dict[str, Any]:
        from resiliencelab.controlplane.database import create_session

        db = create_session()
        try:
            reason = payload.reason if payload else ""
            success, status_msg = request_cancel(db, experiment_id, reason=reason)
            if not success:
                if status_msg == "not_found":
                    raise HTTPException(
                        status_code=404, detail=f"unknown experiment {experiment_id}"
                    )
                # Terminal states and already-cancel-requested are idempotent
                return {
                    "id": experiment_id,
                    "status": status_msg,
                    "message": f"experiment is already {status_msg}",
                }
            db.commit()
            return {"id": experiment_id, "status": status_msg}
        except HTTPException:
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @v1.get("/experiments/{experiment_id}/status")
    async def experiment_status(experiment_id: str) -> dict[str, Any]:
        from resiliencelab.controlplane.database import create_session

        db = create_session()
        try:
            record = db_get_experiment(db, experiment_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
            runs = db_get_runs(db, experiment_id)
            return {
                "id": experiment_id,
                "status": record.status,
                "error": record.error_message,
                "cancellation_reason": record.cancellation_reason,
                "runs": [{"run_id": run.run_id, "status": run.status} for run in runs],
            }
        finally:
            db.close()

    @v1.get("/experiments/{experiment_id}/metrics")
    async def experiment_metrics(experiment_id: str) -> dict[str, Any]:
        raise HTTPException(
            status_code=501,
            detail="metrics endpoint requires local results; use artifacts instead",
        )

    @v1.get("/experiments/{experiment_id}/timeline")
    async def experiment_timeline(experiment_id: str) -> dict[str, Any]:
        raise HTTPException(
            status_code=501,
            detail="timeline endpoint requires local results; use artifacts instead",
        )

    @v1.get("/experiments/{experiment_id}/events")
    async def experiment_events(
        experiment_id: str,
        event_type: str | None = None,
        service: str | None = None,
        request_id: int | None = None,
    ) -> dict[str, Any]:
        raise HTTPException(
            status_code=501,
            detail="events endpoint requires local results; use artifacts instead",
        )

    @v1.get("/experiments/{experiment_id}/report", response_class=PlainTextResponse)
    async def experiment_report(experiment_id: str) -> str:
        raise HTTPException(
            status_code=501,
            detail="report endpoint requires local results; use artifacts instead",
        )

    @v1.get("/experiments/{experiment_id}/analysis")
    async def experiment_analysis(experiment_id: str) -> dict[str, Any]:
        raise HTTPException(
            status_code=501,
            detail="analysis endpoint requires local results; use artifacts instead",
        )

    @v1.get("/benchmarks")
    async def list_benchmarks() -> dict[str, Any]:
        from resiliencelab.experiments.benchmarks import list_standard_benchmarks

        return {"benchmarks": list_standard_benchmarks()}

    @v1.get("/policies")
    async def list_policies() -> dict[str, Any]:
        return {
            "mechanisms": [
                "retry",
                "backoff",
                "jitter",
                "circuit_breaker",
                "timeout",
                "concurrency",
            ]
        }

    @v1.get("/fault-models")
    async def list_fault_models() -> dict[str, Any]:
        from resiliencelab.faults.model import FailureKind, TemporalMode

        return {
            "failure_types": [k.value for k in FailureKind],
            "temporal_modes": [m.value for m in TemporalMode],
        }

    @v1.get("/workloads")
    async def list_workloads() -> dict[str, Any]:
        from resiliencelab.core.schema import WorkloadType

        return {"workload_types": [w.value for w in WorkloadType]}


def _register_local_routes(v1: APIRouter, runtime: LocalRuntime | None) -> None:
    runtime = runtime or LocalRuntime()

    @v1.post("/experiments", status_code=201)
    async def create_experiment(payload: ExperimentCreate) -> dict[str, Any]:
        try:
            spec = parse_experiment(payload.config)
        except (ConfigValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        runtime.registry.register_spec(spec)
        return {"id": spec.id, "name": spec.name}

    @v1.get("/experiments")
    async def list_experiments() -> dict[str, Any]:
        return {"experiments": runtime.registry.spec_ids()}

    @v1.get("/experiments/{experiment_id}")
    async def get_experiment(experiment_id: str) -> dict[str, Any]:
        spec = runtime.registry.get_spec(experiment_id)
        result = runtime.registry.get_result(experiment_id)
        if spec is None and result is not None:
            spec = result.experiment
        if spec is None:
            raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
        return {"experiment": spec.model_dump(mode="json")}

    @v1.post("/experiments/{experiment_id}/run")
    async def run_experiment(
        experiment_id: str, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
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
        return {"id": experiment_id, "status": "running"}

    @v1.post("/experiments/{experiment_id}/cancel")
    async def cancel_experiment(
        experiment_id: str,
        payload: CancelRequest | None = None,
    ) -> dict[str, Any]:
        reason = payload.reason if payload else ""
        success, status_msg = runtime.request_cancel(experiment_id, reason=reason)
        if not success:
            if status_msg == "not_found":
                raise HTTPException(status_code=404, detail=f"unknown experiment {experiment_id}")
            return {
                "id": experiment_id,
                "status": status_msg,
                "message": f"experiment is already {status_msg}",
            }
        return {"id": experiment_id, "status": status_msg}

    @v1.get("/experiments/{experiment_id}/status")
    async def experiment_status(experiment_id: str) -> dict[str, Any]:
        job = runtime.job(experiment_id)
        return {
            "id": experiment_id,
            "status": job["status"],
            "error": job["error"],
        }

    @v1.get("/experiments/{experiment_id}/metrics")
    async def experiment_metrics(experiment_id: str) -> dict[str, Any]:
        result = _result_or_404(runtime, experiment_id)
        return {"metrics_per_run": result.metrics_per_run()}

    @v1.get("/experiments/{experiment_id}/timeline")
    async def experiment_timeline(experiment_id: str) -> dict[str, Any]:
        result = _result_or_404(runtime, experiment_id)
        return {"timeline": [run.timeline for run in result.runs]}

    @v1.get("/experiments/{experiment_id}/events")
    async def experiment_events(
        experiment_id: str,
        event_type: str | None = None,
        service: str | None = None,
        request_id: int | None = None,
    ) -> dict[str, Any]:
        from resiliencelab.analysis.events import filter_events

        result = _result_or_404(runtime, experiment_id)
        events = filter_events(
            result.run_events(),
            event_type=event_type,
            service=service,
            request_id=request_id,
        )
        return {
            "event_schema_version": "1",
            "count": len(events),
            "events": [event.to_dict() for event in events],
        }

    @v1.get("/experiments/{experiment_id}/report", response_class=PlainTextResponse)
    async def experiment_report(experiment_id: str) -> str:
        result = _result_or_404(runtime, experiment_id)
        return build_report(result)

    @v1.get("/experiments/{experiment_id}/analysis")
    async def experiment_analysis(experiment_id: str) -> dict[str, Any]:
        result = _result_or_404(runtime, experiment_id)
        return {"analysis": automatic_analysis(result)}

    @v1.get("/benchmarks")
    async def list_benchmarks() -> dict[str, Any]:
        from resiliencelab.experiments.benchmarks import list_standard_benchmarks

        return {"benchmarks": list_standard_benchmarks()}

    @v1.get("/policies")
    async def list_policies() -> dict[str, Any]:
        return {
            "mechanisms": [
                "retry",
                "backoff",
                "jitter",
                "circuit_breaker",
                "timeout",
                "concurrency",
            ]
        }

    @v1.get("/fault-models")
    async def list_fault_models() -> dict[str, Any]:
        from resiliencelab.faults.model import FailureKind, TemporalMode

        return {
            "failure_types": [k.value for k in FailureKind],
            "temporal_modes": [m.value for m in TemporalMode],
        }

    @v1.get("/workloads")
    async def list_workloads() -> dict[str, Any]:
        from resiliencelab.core.schema import WorkloadType

        return {"workload_types": [w.value for w in WorkloadType]}


app = create_app()
