"""A downstream dependency service with injectable faults."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from resiliencelab.core.clock import Clock
from resiliencelab.core.seeds import generator_for
from resiliencelab.faults.model import FailureKind, FaultEvent, FaultInjector
from resiliencelab.resilience.errors import CallFailure

if TYPE_CHECKING:
    from numpy.random import Generator

FAULT_RNG_SALT = 0x5EED


class DependencyService:
    def __init__(
        self,
        name: str,
        injectors: list[FaultInjector] | None = None,
        seed: int = 0,
        clock: Clock | None = None,
        hang_duration: float = 30.0,
        saturation_delay: float = 0.05,
    ) -> None:
        self.name = name
        self.injectors = list(injectors or [])
        self.seed = seed
        self.clock = clock if clock is not None else Clock()
        self.hang_duration = hang_duration
        self.saturation_delay = saturation_delay
        self.app = FastAPI(title=f"ResilienceLab dependency: {name}")
        self._register_routes()

    def now(self) -> float:
        return self.clock.now()

    def _evaluate(self, now: float, rng: Generator) -> FaultEvent | None:
        for injector in self.injectors:
            event = injector.evaluate(now, rng)
            if event is not None:
                return event
        return None

    async def invoke(self, seed: int, request_id: int) -> None:
        rng = generator_for(seed, request_id, FAULT_RNG_SALT)
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
