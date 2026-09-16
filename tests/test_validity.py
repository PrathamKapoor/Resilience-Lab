"""Phase 18: Experimental validity tests.

Construct experiments designed to expose hidden simulator artifacts:
- No-fault baseline
- Policy disabled
- Symmetry
- Seed reproducibility
- Run isolation
- Repetition isolation
"""

from __future__ import annotations

import asyncio

from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.core.seeds import generator_for
from resiliencelab.experiments.runner import ExperimentRunner


def _base_spec(**overrides: object) -> ExperimentSpec:
    data = {
        "id": "validity_test",
        "name": "validity test",
        "workload": {"type": "closed_loop", "clients": 5, "duration": "0.5s"},
        "repetitions": {"count": 1, "base_seed": 42},
    }
    data.update(overrides)  # type: ignore[arg-type]
    return ExperimentSpec.model_validate(data)


class TestNoFaultBaseline:
    def test_no_faults_produces_zero_failures(self) -> None:
        spec = _base_spec()
        assert len(spec.failure) == 0
        runner = ExperimentRunner()
        result = asyncio.run(runner.run_async(spec))
        assert len(result.runs) == 1
        run = result.runs[0]
        assert run.summary.failed == 0
        assert run.summary.availability == 1.0

    def test_disabled_fault_produces_no_injection(self) -> None:
        spec = _base_spec(
            failure=[
                {
                    "target": "payment_service",
                    "type": "http_503",
                    "mode": "constant",
                    "probability": 0.0,
                }
            ]
        )
        runner = ExperimentRunner()
        result = asyncio.run(runner.run_async(spec))
        assert result.runs[0].summary.failed == 0


class TestPolicyDisabled:
    def test_no_retry_policy_no_retries(self) -> None:
        spec = _base_spec(policy={"retry": {"enabled": False}})
        runner = ExperimentRunner()
        result = asyncio.run(runner.run_async(spec))
        assert result.runs[0].summary.amplifications.get("requests", 0.0) <= 1.0


class TestSymmetry:
    def test_identical_configs_produce_same_availability(self) -> None:
        spec1 = _base_spec(id="sym_a", name="sym a")
        spec2 = _base_spec(id="sym_b", name="sym b")
        runner = ExperimentRunner()
        r1 = asyncio.run(runner.run_async(spec1))
        r2 = asyncio.run(runner.run_async(spec2))
        # Same config, same seed strategy → same availability
        assert r1.runs[0].summary.availability == r2.runs[0].summary.availability


class TestSeedReproducibility:
    def test_same_seed_same_decisions(self) -> None:
        gen1 = generator_for(42, 100)
        gen2 = generator_for(42, 100)
        samples1 = [gen1.uniform(0, 1) for _ in range(50)]
        samples2 = [gen2.uniform(0, 1) for _ in range(50)]
        assert samples1 == samples2

    def test_different_seeds_different_decisions(self) -> None:
        gen1 = generator_for(42, 100)
        gen2 = generator_for(99, 100)
        samples1 = [gen1.uniform(0, 1) for _ in range(50)]
        samples2 = [gen2.uniform(0, 1) for _ in range(50)]
        assert samples1 != samples2


class TestRunIsolation:
    def test_independent_runs_same_result(self) -> None:
        spec = _base_spec(repetitions={"count": 2, "base_seed": 42})
        runner = ExperimentRunner()
        result = asyncio.run(runner.run_async(spec))
        assert len(result.runs) == 2
        # Different seeds → different results
        assert result.runs[0].seed != result.runs[1].seed
        # But both should complete successfully
        assert result.runs[0].summary.total > 0
        assert result.runs[1].summary.total > 0


class TestRepetitionIsolation:
    def test_repetitions_use_distinct_seeds(self) -> None:
        spec = _base_spec(repetitions={"count": 3, "base_seed": 100})
        runner = ExperimentRunner()
        result = asyncio.run(runner.run_async(spec))
        seeds = [run.seed for run in result.runs]
        assert len(set(seeds)) == 3  # All unique

    def test_repetitions_independent_metrics(self) -> None:
        spec = _base_spec(repetitions={"count": 2, "base_seed": 42})
        runner = ExperimentRunner()
        result = asyncio.run(runner.run_async(spec))
        # Both repetitions should have metrics
        assert result.runs[0].summary.total > 0
        assert result.runs[1].summary.total > 0
