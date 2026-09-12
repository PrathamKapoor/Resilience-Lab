from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from resiliencelab.api.app import Runtime, create_app
from resiliencelab.core.config import parse_experiment


def _client() -> TestClient:
    return TestClient(create_app(Runtime()))


def _tiny_config() -> dict:
    return {
        "experiment": {"id": "exp_api", "name": "api smoke"},
        "workload": {"type": "closed_loop", "clients": 1, "duration": "0.2s", "warmup": "0s"},
        "repetitions": {"count": 1, "base_seed": 3},
    }


def test_catalog_endpoints() -> None:
    client = _client()
    assert client.get("/api/v1/benchmarks").status_code == 200
    assert client.get("/api/v1/policies").status_code == 200
    assert client.get("/api/v1/fault-models").status_code == 200
    assert client.get("/api/v1/workloads").status_code == 200


def test_create_and_get_experiment() -> None:
    client = _client()
    response = client.post("/api/v1/experiments", json={"config": _tiny_config()})
    assert response.status_code == 201
    assert response.json()["id"] == "exp_api"
    listed = client.get("/api/v1/experiments").json()
    assert "exp_api" in listed["experiments"]
    fetched = client.get("/api/v1/experiments/exp_api").json()
    assert fetched["experiment"]["id"] == "exp_api"


def test_run_completes_and_metrics_available() -> None:
    client = _client()
    client.post("/api/v1/experiments", json={"config": _tiny_config()})
    assert client.post("/api/v1/experiments/exp_api/run").status_code == 200
    assert client.get("/api/v1/experiments/exp_api/status").json()["status"] == "completed"
    metrics = client.get("/api/v1/experiments/exp_api/metrics").json()
    assert metrics["metrics_per_run"]
    timeline = client.get("/api/v1/experiments/exp_api/timeline").json()
    assert timeline["timeline"]
    report = client.get("/api/v1/experiments/exp_api/report")
    assert report.status_code == 200 and "exp_api" in report.text


async def test_runtime_submit_runs_in_background() -> None:
    runtime = Runtime()
    spec = parse_experiment(
        {
            "experiment": {"id": "exp_bg", "name": "bg"},
            "workload": {"type": "closed_loop", "clients": 1, "duration": "0.2s", "warmup": "0s"},
            "repetitions": {"count": 1, "base_seed": 5},
        }
    )
    await runtime.submit(spec)
    await asyncio.sleep(5)
    job = runtime.job("exp_bg")
    assert job["status"] == "completed", job.get("error")
    assert runtime.registry.get_result("exp_bg") is not None
