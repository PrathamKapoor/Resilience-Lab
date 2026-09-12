"""Workload generation: reproducible traffic driving the system under test."""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

from resiliencelab.core.clock import Clock
from resiliencelab.core.schema import ArrivalDistribution, WorkloadSpec, WorkloadType
from resiliencelab.core.seeds import generator_for
from resiliencelab.metrics.collector import MetricsCollector

if TYPE_CHECKING:
    from numpy.random import Generator


class ResponseLike(Protocol):
    @property
    def status_code(self) -> int: ...


SendCallable = Callable[[int], Awaitable[ResponseLike]]


class WorkloadGenerator:
    def __init__(
        self,
        spec: WorkloadSpec,
        send: SendCallable,
        metrics: MetricsCollector,
        seed: int,
        clock: Clock | None = None,
    ) -> None:
        self.spec = spec
        self.send = send
        self.metrics = metrics
        self.seed = seed
        self.clock = clock if clock is not None else Clock()

    async def run(self) -> None:
        spec = self.spec
        if spec.warmup > 0:
            self.metrics.set_recording(False)
            try:
                await self._drive(spec.warmup)
            finally:
                self.metrics.set_recording(True)
        await self._drive(spec.duration)

    async def _drive(self, duration: float) -> None:
        mode = self.spec.type
        if mode in (WorkloadType.OPEN_LOOP, WorkloadType.CONSTANT_RATE):
            await self._open_loop(duration)
        elif mode is WorkloadType.RAMP:
            await self._ramp(duration)
        else:
            await self._closed_loop(duration)

    async def _closed_loop(self, duration: float) -> None:
        counter = itertools.count()
        stop = asyncio.Event()

        async def client_loop() -> None:
            while not stop.is_set():
                await self._issue(next(counter))
                await asyncio.sleep(0)

        tasks = [asyncio.create_task(client_loop()) for _ in range(self.spec.clients)]
        try:
            await asyncio.sleep(duration)
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _open_loop(self, duration: float) -> None:
        counter = itertools.count()
        rng = generator_for(self.seed, 200_000)
        deadline = time.perf_counter() + duration

        while time.perf_counter() < deadline:
            await self._issue(next(counter))
            await asyncio.sleep(self._next_gap(rng))

    async def _ramp(self, duration: float) -> None:
        counter = itertools.count()
        deadline = time.perf_counter() + duration
        start_rate = max(1.0, self.spec.arrival_rate * 0.1)

        while time.perf_counter() < deadline:
            await self._issue(next(counter))
            elapsed = duration - (deadline - time.perf_counter())
            rate = start_rate + (self.spec.arrival_rate - start_rate) * (elapsed / duration)
            await asyncio.sleep(1.0 / max(rate, 1e-9))

    def _next_gap(self, rng: Generator) -> float:
        rate = self.spec.arrival_rate
        if self.spec.distribution is ArrivalDistribution.POISSON:
            return float(rng.exponential(1.0 / rate))
        return 1.0 / rate

    async def _issue(self, request_id: int) -> None:
        started = time.perf_counter()
        try:
            response = await self.send(request_id)
            status = response.status_code
            success = status < 400
            timeout = False
        except Exception as exc:  # noqa: BLE001
            status = None
            success = False
            timeout = isinstance(exc, TimeoutError)
        latency = time.perf_counter() - started
        self.metrics.record(
            MetricsCollector.REQUEST,
            request_id=request_id,
            status=status,
            success=success,
            timeout=timeout,
            latency=latency,
        )
