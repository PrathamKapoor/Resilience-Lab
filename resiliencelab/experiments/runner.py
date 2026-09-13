"""Orchestrates a full experiment: SUT + dependency + workload + faults + metrics."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from resiliencelab.analysis.recovery import detect_recovery
from resiliencelab.core.builders import build_fault_spec, build_policy
from resiliencelab.core.clock import Clock
from resiliencelab.core.policies import PolicyResolver
from resiliencelab.core.schema import ExperimentSpec, SeedStrategy, ServiceSpec
from resiliencelab.core.seeds import generator, generator_for
from resiliencelab.events import EventEmitter, EventType
from resiliencelab.experiments.provenance import capture_environment, hash_config
from resiliencelab.experiments.result import ExperimentResult, RunResult
from resiliencelab.faults.model import FaultInjector
from resiliencelab.metrics.collector import MetricsCollector
from resiliencelab.metrics.timeline import build_timeline
from resiliencelab.metrics.transforms import summarize_downstream, summarize_requests
from resiliencelab.resilience.circuit_breaker import CircuitState
from resiliencelab.resilience.jitter import Rng
from resiliencelab.services.client import ResilientClient
from resiliencelab.services.dependency import FAULT_RNG_SALT, DependencyService
from resiliencelab.services.network import NETWORK_RNG_SALT, network_delay, resolve_network_link
from resiliencelab.services.sut import ServiceResponse, SystemUnderTest
from resiliencelab.workloads.generator import WorkloadGenerator

_CIRCUIT_EVENTS = {
    CircuitState.CLOSED: "circuit_close",
    CircuitState.OPEN: "circuit_open",
    CircuitState.HALF_OPEN: "circuit_half_open",
}

_CIRCUIT_EVENT_TYPES = {
    CircuitState.CLOSED: EventType.CIRCUIT_CLOSED,
    CircuitState.OPEN: EventType.CIRCUIT_OPENED,
    CircuitState.HALF_OPEN: EventType.CIRCUIT_HALF_OPENED,
}


class ExperimentRunner:
    def __init__(self) -> None:
        pass

    def run(self, spec: ExperimentSpec) -> ExperimentResult:
        return asyncio.run(self.run_async(spec))

    async def run_async(self, spec: ExperimentSpec) -> ExperimentResult:
        seeds = self._seeds(spec)
        policy_name = build_policy(spec.policy).name
        lifecycle = EventEmitter(spec.id, "experiment", clock=Clock().now)
        lifecycle.emit(
            EventType.EXPERIMENT_STARTED,
            metadata={
                "benchmark": spec.id,
                "repetitions": len(seeds),
                "policy": policy_name,
            },
        )
        runs: list[RunResult] = []
        try:
            for index, seed in enumerate(seeds):
                runs.append(await self._run_once(spec, seed, index))
        except Exception as exc:  # noqa: BLE001
            lifecycle.emit(EventType.EXPERIMENT_FAILED, reason=str(exc))
            raise
        lifecycle.emit(EventType.EXPERIMENT_COMPLETED, metadata={"runs": len(runs)})
        return ExperimentResult(
            experiment=spec,
            policy_name=policy_name,
            config_hash=hash_config(spec),
            runs=runs,
            environment=capture_environment(),
            events=lifecycle.events(),
        )

    def _seeds(self, spec: ExperimentSpec) -> list[int]:
        count = spec.repetitions.count
        base = spec.repetitions.base_seed
        if spec.repetitions.seed_strategy is SeedStrategy.RANDOM:
            rng = generator(base)
            return [int(rng.integers(0, 2**31 - 1)) for _ in range(count)]
        return [base + i for i in range(count)]

    def _service_names(self, spec: ExperimentSpec) -> list[str]:
        if spec.system.services:
            return list(spec.system.call_order())
        return ["payment_service"]

    def _service_spec(self, spec: ExperimentSpec, name: str) -> ServiceSpec | None:
        for service in spec.system.services:
            if service.name == name:
                return service
        return None

    def _injectors_by_service(
        self, spec: ExperimentSpec, warmup: float
    ) -> dict[str, list[FaultInjector]]:
        routed: dict[str, list[FaultInjector]] = {}
        for failure in spec.failure:
            fault_spec = replace(build_fault_spec(failure), start=failure.start + warmup)
            if spec.system.services:
                routed.setdefault(failure.target, []).append(FaultInjector(fault_spec))
            else:
                routed.setdefault("payment_service", []).append(FaultInjector(fault_spec))
        return routed

    async def _run_once(self, spec: ExperimentSpec, seed: int, index: int) -> RunResult:
        run_id = f"{spec.id}/run-{index}"
        clock = Clock()
        metrics = MetricsCollector(spec.id, run_id, seed, clock=clock.now)
        warmup = spec.workload.warmup
        routed = self._injectors_by_service(spec, warmup)
        names = self._service_names(spec)
        indices = {name: index for index, name in enumerate(names)}

        policies = {
            name: build_policy(PolicyResolver(spec.policy, spec.policies).resolve(name))
            for name in names
        }
        for name, policy in policies.items():
            if policy.circuit_breaker is not None:

                def on_transition(
                    old: CircuitState, new: CircuitState, service: str = name
                ) -> None:
                    metrics.record(
                        MetricsCollector.EVENT,
                        dependency=service,
                        event=_CIRCUIT_EVENTS[new],
                        from_state=old.value,
                        to_state=new.value,
                    )
                    metrics.emit(
                        _CIRCUIT_EVENT_TYPES[new],
                        target_service=service,
                        reason="threshold" if new is CircuitState.OPEN else None,
                        metadata={"from_state": old.value, "to_state": new.value},
                    )

                policy.circuit_breaker.on_transition(on_transition)

        dependencies: dict[str, DependencyService] = {}
        network_links: dict[str, Any] = {}
        clients: dict[str, ResilientClient] = {}
        for name in names:
            service_spec = self._service_spec(spec, name)
            dependencies[name] = DependencyService(
                name,
                routed.get(name, []),
                seed=seed,
                clock=clock,
                salt=FAULT_RNG_SALT + indices[name],
                processing=service_spec.processing if service_spec else None,
                capacity=service_spec.capacity if service_spec else None,
                metrics=metrics,
            )
            network_links[name] = resolve_network_link(spec.system.network, "order_api", name)
            clients[name] = ResilientClient(policies[name], metrics)

        async def downstream(request_id: int, rng: Rng) -> object:
            result: object = None
            for name in names:
                dependency = dependencies[name]
                attempt_context: dict[str, Any] = {
                    "source_service": "order_api",
                    "target_service": name,
                }
                index = indices[name]
                link = network_links[name]

                async def operation(
                    dep: DependencyService = dependency,
                    ctx: dict[str, Any] = attempt_context,
                    idx: int = index,
                    nw: Any = link,
                    target: str = name,
                ) -> None:
                    rng_nw = generator_for(seed, request_id, NETWORK_RNG_SALT, idx)
                    delay = network_delay(nw, rng_nw)
                    ctx["network_latency"] = delay
                    if delay > 0:
                        await asyncio.sleep(delay)
                    if nw is not None:
                        metrics.emit(
                            EventType.NETWORK_DELAY_APPLIED,
                            request_id=request_id,
                            attempt=ctx.get("attempt"),
                            source_service="order_api",
                            target_service=target,
                            metadata={
                                "base": nw.latency,
                                "jitter": nw.jitter,
                                "delay": delay,
                            },
                        )
                    await dep.invoke(seed, request_id, attempt_context=ctx)

                result = await clients[name].execute(
                    operation,
                    rng=rng,
                    request_id=request_id,
                    dependency=name,
                    attempt_context=attempt_context,
                )
            return result

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
        service_metrics = {
            name: snapshot
            for name in names
            if (snapshot := dependencies[name].capacity_snapshot()) is not None
        }
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
            service_metrics=service_metrics,
            events=metrics.events(),
        )
