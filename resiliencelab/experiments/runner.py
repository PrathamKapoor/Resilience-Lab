"""Orchestrates a full experiment: SUT + dependency + workload + faults + metrics."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from resiliencelab.analysis.recovery import detect_recovery
from resiliencelab.core.builders import build_fault_spec, build_policy
from resiliencelab.core.clock import Clock
from resiliencelab.core.schema import ExperimentSpec, SeedStrategy
from resiliencelab.core.seeds import generator
from resiliencelab.experiments.provenance import capture_environment, hash_config
from resiliencelab.experiments.result import ExperimentResult, RunResult
from resiliencelab.faults.model import FaultInjector
from resiliencelab.metrics.collector import MetricsCollector
from resiliencelab.metrics.timeline import build_timeline
from resiliencelab.metrics.transforms import summarize_downstream, summarize_requests
from resiliencelab.resilience.circuit_breaker import CircuitState
from resiliencelab.resilience.jitter import Rng
from resiliencelab.services.client import ResilientClient
from resiliencelab.services.dependency import DependencyService
from resiliencelab.services.sut import ServiceResponse, SystemUnderTest
from resiliencelab.workloads.generator import WorkloadGenerator

_CIRCUIT_EVENTS = {
    CircuitState.CLOSED: "circuit_close",
    CircuitState.OPEN: "circuit_open",
    CircuitState.HALF_OPEN: "circuit_half_open",
}


class ExperimentRunner:
    def __init__(self) -> None:
        pass

    def run(self, spec: ExperimentSpec) -> ExperimentResult:
        return asyncio.run(self.run_async(spec))

    async def run_async(self, spec: ExperimentSpec) -> ExperimentResult:
        seeds = self._seeds(spec)
        policy_name = build_policy(spec.policy).name
        runs: list[RunResult] = []
        for index, seed in enumerate(seeds):
            runs.append(await self._run_once(spec, seed, index))
        return ExperimentResult(
            experiment=spec,
            policy_name=policy_name,
            config_hash=hash_config(spec),
            runs=runs,
            environment=capture_environment(),
        )

    def _seeds(self, spec: ExperimentSpec) -> list[int]:
        count = spec.repetitions.count
        base = spec.repetitions.base_seed
        if spec.repetitions.seed_strategy is SeedStrategy.RANDOM:
            rng = generator(base)
            return [int(rng.integers(0, 2**31 - 1)) for _ in range(count)]
        return [base + i for i in range(count)]

    def _injectors(self, spec: ExperimentSpec, warmup: float) -> list[FaultInjector]:
        injectors: list[FaultInjector] = []
        for failure in spec.failure:
            fault_spec = replace(build_fault_spec(failure), start=failure.start + warmup)
            injectors.append(FaultInjector(fault_spec))
        return injectors

    async def _run_once(self, spec: ExperimentSpec, seed: int, index: int) -> RunResult:
        run_id = f"{spec.id}/run-{index}"
        clock = Clock()
        metrics = MetricsCollector(spec.id, run_id, seed, clock=clock.now)
        policy = build_policy(spec.policy)

        if policy.circuit_breaker is not None:
            policy.circuit_breaker.on_transition(
                lambda old, new: metrics.record(
                    MetricsCollector.EVENT,
                    event=_CIRCUIT_EVENTS[new],
                    from_state=old.value,
                    to_state=new.value,
                )
            )

        warmup = spec.workload.warmup
        injectors = self._injectors(spec, warmup)
        dependency = DependencyService("payment_service", injectors, seed=seed, clock=clock)
        dep_client = ResilientClient(policy, metrics)

        async def downstream(request_id: int, rng: Rng) -> object:
            async def operation() -> None:
                await dependency.invoke(seed, request_id)

            return await dep_client.execute(
                operation,
                rng=rng,
                request_id=request_id,
                dependency=dependency.name,
            )

        sut = SystemUnderTest("order_api", downstream, seed=seed)

        async def send(request_id: int) -> ServiceResponse:
            return await sut.handle(request_id, seed)

        workload = WorkloadGenerator(spec.workload, send, metrics, seed, clock)
        await workload.run()

        records = metrics.records()
        timeline = build_timeline(records, bucket=1.0)
        throughput = [(b["t"], b["rps"]) for b in timeline]
        latency_series = [(b["t"], b["p95"]) for b in timeline]
        analysis = spec.analysis
        recovery = detect_recovery(
            throughput,
            latency_series=latency_series,
            baseline_window=analysis.baseline_window or 10.0,
            availability_threshold=analysis.availability_threshold,
            latency_tolerance=analysis.latency_tolerance,
            stability_window=analysis.stability_window,
        )
        backoff_seconds = sum(
            float(e["delay"])
            for e in records
            if e.get("kind") == MetricsCollector.EVENT
            and e.get("event") == "retry"
            and e.get("delay")
        )
        return RunResult(
            run_id=run_id,
            seed=seed,
            summary=summarize_requests(records),
            downstream=summarize_downstream(records),
            recovery=recovery,
            timeline=timeline,
            record_count=len(records),
            backoff_seconds=backoff_seconds,
            records=records,
        )
