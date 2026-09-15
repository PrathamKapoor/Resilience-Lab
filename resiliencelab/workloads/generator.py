"""Workload generation: reproducible traffic driving the system under test."""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from resiliencelab.core.cancellation import CancellationToken
from resiliencelab.core.clock import Clock
from resiliencelab.core.schema import WorkloadSpec, WorkloadType
from resiliencelab.core.seeds import generator_for
from resiliencelab.events import EventType
from resiliencelab.metrics.collector import MetricsCollector
from resiliencelab.workloads.arrivals import ArrivalModel


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
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.spec = spec
        self.send = send
        self.metrics = metrics
        self.seed = seed
        self.clock = clock if clock is not None else Clock()
        self._cancellation_token = cancellation_token

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
        self._check_cancel()
        if self.spec.type is WorkloadType.CLOSED_LOOP:
            await self._closed_loop(duration)
            return
        await self._arrival_loop(duration)

    def _check_cancel(self) -> None:
        if self._cancellation_token is not None:
            self._cancellation_token.raise_if_cancelled()

    async def _arrival_loop(self, duration: float) -> None:
        model = ArrivalModel(self.spec)
        rng = generator_for(self.seed, 200_000)
        counter = itertools.count()
        start = time.perf_counter()
        deadline = start + duration
        while time.perf_counter() < deadline:
            self._check_cancel()
            await self._issue(next(counter))
            elapsed = time.perf_counter() - start
            await asyncio.sleep(max(model.gap(elapsed, rng), 0.0))

    async def _closed_loop(self, duration: float) -> None:
        counter = itertools.count()
        stop = asyncio.Event()

        async def client_loop() -> None:
            while not stop.is_set():
                self._check_cancel()
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

    async def _issue(self, request_id: int) -> None:
        self.metrics.emit(EventType.REQUEST_STARTED, request_id=request_id, operation="/")
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
        if success:
            self.metrics.emit(
                EventType.REQUEST_COMPLETED,
                request_id=request_id,
                operation="/",
                status=status,
                metadata={"latency": latency},
            )
        else:
            self.metrics.emit(
                EventType.REQUEST_FAILED,
                request_id=request_id,
                operation="/",
                status=status,
                reason="timeout" if timeout else "failed",
                metadata={"latency": latency, "timeout": timeout},
            )
