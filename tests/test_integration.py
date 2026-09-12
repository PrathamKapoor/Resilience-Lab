from __future__ import annotations

import pytest

from resiliencelab.core.config import parse_experiment
from resiliencelab.experiments.runner import ExperimentRunner
from resiliencelab.metrics.collector import MetricsCollector


def _spec(**overrides) -> dict:
    config = {
        "experiment": {
            "id": "exp_integration",
            "name": "integration test",
            "version": 1,
            "system": {"replicas": 1, "workers_per_replica": 1},
            "workload": {
                "type": "closed_loop",
                "clients": 4,
                "arrival_rate": 100,
                "duration": "2s",
                "warmup": "0.2s",
            },
            "failure": [
                {
                    "target": "payment_service",
                    "type": "http_503",
                    "mode": "burst",
                    "probability": 1.0,
                    "duration": "5s",
                }
            ],
            "policy": {
                "retry": {"enabled": True, "max_attempts": 3},
                "backoff": {"type": "fixed", "base": "0.01s", "maximum": "0.01s"},
                "timeout": {"total": "1s"},
            },
            "repetitions": {"count": 1, "seed_strategy": "deterministic", "base_seed": 7},
        }
    }
    config["experiment"].update(overrides)
    return config


@pytest.mark.asyncio
async def test_runner_produces_results() -> None:
    spec = parse_experiment(_spec())
    runner = ExperimentRunner()
    result = await runner.run_async(spec)
    assert result.runs
    run = result.runs[0]
    assert run.record_count > 0
    assert run.summary.total > 0


@pytest.mark.asyncio
async def test_baseline_no_failure_is_available() -> None:
    spec = parse_experiment(
        _spec(
            workload={
                "type": "closed_loop",
                "clients": 3,
                "duration": "1s",
                "warmup": "0.1s",
                "arrival_rate": 100,
            },
            failure=[],
        )
    )
    runner = ExperimentRunner()
    result = await runner.run_async(spec)
    run = result.runs[0]
    assert run.summary.availability > 0.9


@pytest.mark.asyncio
async def test_retry_amplifies_downstream_calls() -> None:
    spec = parse_experiment(_spec())
    runner = ExperimentRunner()
    result = await runner.run_async(spec)
    run = result.runs[0]
    assert run.summary.amplifications["requests"] >= 1.0


def _cascade_spec() -> dict:
    config = _spec()
    experiment = config["experiment"]
    experiment["system"] = {
        "services": [
            {"name": "payment_service"},
            {"name": "inventory_service", "depends_on": ["payment_service"]},
        ]
    }
    experiment["failure"] = [
        {
            "target": "inventory_service",
            "type": "http_500",
            "mode": "burst",
            "probability": 1.0,
            "duration": "5s",
        }
    ]
    return config


@pytest.mark.asyncio
async def test_cascade_across_two_dependencies() -> None:
    spec = parse_experiment(_cascade_spec())
    runner = ExperimentRunner()
    result = await runner.run_async(spec)
    run = result.runs[0]
    assert run.summary.total > 0
    assert run.summary.availability == pytest.approx(0.0)
    touched = {
        r.get("dependency")
        for r in run.records
        if r.get("kind") == MetricsCollector.DOWNSTREAM and r.get("dependency") is not None
    }
    assert touched == {"payment_service", "inventory_service"}


@pytest.mark.asyncio
async def test_faults_routed_to_declared_target_only() -> None:
    spec = parse_experiment(_cascade_spec())
    runner = ExperimentRunner()
    result = await runner.run_async(spec)
    records = result.runs[0].records
    by_dependency: dict[str, list[bool]] = {}
    for r in records:
        if r.get("kind") == MetricsCollector.DOWNSTREAM:
            by_dependency.setdefault(str(r.get("dependency")), []).append(bool(r.get("success")))
    assert set(by_dependency) == {"payment_service", "inventory_service"}
    assert by_dependency["payment_service"] and all(by_dependency["payment_service"])
    assert by_dependency["inventory_service"] and not any(by_dependency["inventory_service"])
