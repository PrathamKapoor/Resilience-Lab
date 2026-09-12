"""ResilienceLab REST API (FastAPI)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from resiliencelab.core.config import ConfigValidationError, parse_experiment
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.experiments.registry import ExperimentRegistry
from resiliencelab.experiments.report import automatic_analysis, build_report
from resiliencelab.experiments.result import ExperimentResult
from resiliencelab.experiments.runner import ExperimentRunner


class ExperimentCreate(BaseModel):
    config: dict[str, Any]


class Runtime:
    def __init__(self) -> None:
        self.registry = ExperimentRegistry()
        self.runner = ExperimentRunner()
        self.jobs: dict[str, dict[str, Any]] = {}

    async def submit(self, spec: ExperimentSpec) -> str:
        self.registry.register_spec(spec)
        job_id = spec.id
        self.jobs[job_id] = {"status": "running", "result": None, "error": None}
        asyncio.create_task(self.execute_and_store(spec))
        return job_id

    async def execute_and_store(self, spec: ExperimentSpec) -> None:
        try:
            result = await self.runner.run_async(spec)
        except Exception as exc:  # noqa: BLE001
            self.jobs[spec.id] = {"status": "failed", "result": None, "error": str(exc)}
            return
        self.registry.register_result(result)
        self.jobs[spec.id] = {"status": "completed", "result": result, "error": None}

    def job(self, experiment_id: str) -> dict[str, Any]:
        return self.jobs.get(experiment_id, {"status": "unknown", "result": None, "error": None})


def _result_or_404(runtime: Runtime, experiment_id: str) -> ExperimentResult:
    result = runtime.registry.get_result(experiment_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no result for {experiment_id}")
    return result


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime()
    app = FastAPI(title="ResilienceLab API", version="0.1.0")
    v1 = APIRouter(prefix="/api/v1")

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
        if spec is None:
            result = runtime.registry.get_result(experiment_id)
            if result is not None:
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
        background_tasks.add_task(runtime.execute_and_store, spec)
        return {"id": experiment_id, "status": "running"}

    @v1.post("/experiments/{experiment_id}/cancel")
    async def cancel_experiment(experiment_id: str) -> dict[str, Any]:
        raise HTTPException(status_code=501, detail="cancellation not yet implemented")

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

    app.include_router(v1)
    return app


app = create_app()
