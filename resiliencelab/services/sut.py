"""The system under test: a FastAPI service whose resilience is being measured.

For experiments, the :meth:`SystemUnderTest.handle` coroutine is invoked
directly in-process (deterministic and free of transport overhead). The FastAPI
route reuses the same logic for real HTTP deployments.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from resiliencelab.core.seeds import generator_for
from resiliencelab.resilience.errors import (
    CallFailure,
    CircuitOpenError,
    ConcurrencyLimitExceeded,
    DeadlineExceeded,
)
from resiliencelab.resilience.jitter import Rng

DownstreamCallable = Callable[[int, Rng], Awaitable[object]]


@dataclass
class ServiceResponse:
    status_code: int
    body: dict[str, Any] | None = None


class SystemUnderTest:
    def __init__(
        self,
        name: str,
        downstream: DownstreamCallable,
        seed: int = 0,
    ) -> None:
        self.name = name
        self.downstream = downstream
        self.seed = seed
        self.app = FastAPI(title=f"ResilienceLab SUT: {name}")
        self._register_routes()

    async def handle(self, request_id: int, seed: int) -> ServiceResponse:
        rng = generator_for(seed, request_id)
        try:
            await self.downstream(request_id, rng)
        except CircuitOpenError:
            return ServiceResponse(status_code=503, body={"error": "circuit open"})
        except DeadlineExceeded:
            return ServiceResponse(status_code=504, body={"error": "deadline exceeded"})
        except ConcurrencyLimitExceeded:
            return ServiceResponse(status_code=429, body={"error": "overloaded"})
        except CallFailure as exc:
            status = exc.status if exc.status is not None else 502
            return ServiceResponse(status_code=status, body={"error": "dependency failed"})
        return ServiceResponse(status_code=200, body={"ok": True})

    def _register_routes(self) -> None:
        @self.app.post("/order")
        async def order(request: Request) -> JSONResponse:
            request_id = int(request.headers.get("x-request-id", "0"))
            seed = int(request.headers.get("x-seed", str(self.seed)))
            response = await self.handle(request_id, seed)
            return JSONResponse(response.body or {}, status_code=response.status_code)
