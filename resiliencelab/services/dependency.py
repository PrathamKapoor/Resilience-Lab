"""A downstream dependency service with injectable faults and simulated
processing, capacity, and (caller-side) network behavior."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from resiliencelab.core.clock import Clock
from resiliencelab.core.schema import CapacitySpec, ProcessingSpec
from resiliencelab.core.seeds import generator_for
from resiliencelab.faults.model import FailureKind, FaultEvent, FaultInjector
from resiliencelab.metrics.collector import MetricsCollector
from resiliencelab.resilience.errors import CallFailure
from resiliencelab.services.capacity import ServiceCapacity, ServiceSaturated
from resiliencelab.services.processing import sample_processing_latency

if TYPE_CHECKING:
    from numpy.random import Generator

FAULT_RNG_SALT = 0x5EED
PROCESSING_RNG_SALT = 0x7072


class DependencyService:
    def __init__(
        self,
        name: str,
        injectors: list[FaultInjector] | None = None,
        seed: int = 0,
        clock: Clock | None = None,
        hang_duration: float = 30.0,
        saturation_delay: float = 0.05,
        salt: int = FAULT_RNG_SALT,
        processing: ProcessingSpec | None = None,
        capacity: CapacitySpec | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self.name = name
        self.injectors = list(injectors or [])
        self.seed = seed
        self.clock = clock if clock is not None else Clock()
        self.hang_duration = hang_duration
        self.saturation_delay = saturation_delay
        self.salt = salt
        self.processing = processing
        self._capacity = (
            ServiceCapacity(capacity.max_concurrency, capacity.queue_limit)
            if capacity is not None
            else None
        )
        self._metrics = metrics
        self.app = FastAPI(title=f"ResilienceLab dependency: {name}")
        self._register_routes()

    def now(self) -> float:
        return self.clock.now()

    def capacity_snapshot(self) -> dict[str, float] | None:
        if self._capacity is None:
            return None
        return self._capacity.snapshot()

    def _evaluate(self, now: float, rng: Generator) -> FaultEvent | None:
        for injector in self.injectors:
            event = injector.evaluate(now, rng)
            if event is not None:
                return event
        return None

    async def invoke(
        self,
        seed: int,
        request_id: int,
        *,
        attempt_context: dict[str, Any] | None = None,
    ) -> None:
        rng = generator_for(seed, request_id, self.salt)

        queue_wait = 0.0
        if self._capacity is not None:
            try:
                queue_wait = await self._capacity.acquire()
            except ServiceSaturated:
                if attempt_context is not None:
                    attempt_context["service_rejected"] = True
                self._record_event(request_id, "service_rejected", reason="capacity")
                raise ServiceSaturated(f"{self.name}: capacity saturated") from None
            if attempt_context is not None:
                attempt_context["queue_wait"] = queue_wait
            if queue_wait > 0:
                self._record_event(request_id, "service_queued", queue_wait=queue_wait)

        try:
            proc_rng = generator_for(seed, request_id, self.salt, PROCESSING_RNG_SALT)
            processing = sample_processing_latency(self.processing, proc_rng)
            if attempt_context is not None:
                attempt_context["processing_latency"] = processing
            if processing > 0:
                await asyncio.sleep(processing)

            event = self._evaluate(self.now(), rng)
            if event is None:
                return
            kind = event.kind
            if kind is FailureKind.LATENCY or kind is FailureKind.LATENCY_SPIKE:
                await asyncio.sleep(event.latency)
                return
            if kind is FailureKind.TIMEOUT:
                await asyncio.sleep(self.hang_duration)
                return
            if kind is FailureKind.CONNECTION_RESET:
                raise ConnectionResetError(f"{self.name}: connection reset")
            if kind is FailureKind.CONNECTION_REFUSED:
                raise ConnectionRefusedError(f"{self.name}: connection refused")
            if kind is FailureKind.SATURATION:
                await asyncio.sleep(self.saturation_delay)
                return
            status = event.status_code or 503
            raise CallFailure(f"{self.name}: {kind.value}", status=status)
        finally:
            if self._capacity is not None:
                await self._capacity.release()

    def _record_event(self, request_id: int, event: str, **fields: Any) -> None:
        if self._metrics is None:
            return
        self._metrics.record(
            MetricsCollector.EVENT,
            request_id=request_id,
            dependency=self.name,
            event=event,
            **fields,
        )

    def _register_routes(self) -> None:
        @self.app.get("/health")
        async def health() -> dict[str, str]:
            return {"service": self.name, "status": "healthy"}

        @self.app.post("/process")
        async def process(request: Request) -> JSONResponse:
            seed = int(request.headers.get("x-seed", str(self.seed)))
            request_id = int(request.headers.get("x-request-id", "0"))
            try:
                await self.invoke(seed, request_id)
            except CallFailure as exc:
                return JSONResponse({"error": exc.args[0]}, status_code=exc.status or 503)
            except (ConnectionError, OSError):
                return JSONResponse({"error": "connection failure"}, status_code=502)
            return JSONResponse({"service": self.name, "ok": True})
