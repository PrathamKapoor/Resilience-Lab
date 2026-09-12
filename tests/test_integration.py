from __future__ import annotations

import pytest

from resiliencelab.core.config import parse_experiment
from resiliencelab.experiments.runner import ExperimentRunner


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
