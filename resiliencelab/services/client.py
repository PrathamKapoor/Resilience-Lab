"""A resilient caller that executes an operation under a resilience policy.

The operation is an arbitrary async callable (in-process for experiments, or
an HTTP call in a distributed deployment). Attempts, retries, and resilience
events are recorded as metrics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from resiliencelab.metrics.collector import MetricsCollector
from resiliencelab.resilience.errors import CallFailure
from resiliencelab.resilience.jitter import Rng
from resiliencelab.resilience.policy import PolicyExecutor, ResiliencePolicy

Operation = Callable[[], Awaitable[object]]


class ResilientClient:
    def __init__(
        self,
        policy: ResiliencePolicy,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self.policy = policy
        self.metrics = metrics

    async def execute(
        self,
        operation: Operation,
        *,
        rng: Rng,
        request_id: int,
        dependency: str | None = None,
        attempt_context: dict[str, Any] | None = None,
    ) -> object:
        last_status: dict[str, int | None] = {"status": None}

        def on_event(event: str, **fields: object) -> None:
            if self.metrics is None:
                return
            if event == "attempt":
                context = attempt_context or {}
                self.metrics.record(
                    MetricsCollector.DOWNSTREAM,
                    request_id=request_id,
                    dependency=dependency,
                    policy=self.policy.name,
                    attempt=fields.get("attempt"),
                    success=fields.get("success"),
                    timeout=fields.get("timeout"),
                    status=fields.get("status")
                    if fields.get("status") is not None
                    else last_status["status"],
                    latency=fields.get("duration"),
                    network_latency=context.get("network_latency"),
                    processing_latency=context.get("processing_latency"),
                    queue_wait=context.get("queue_wait"),
                    service_rejected=context.get("service_rejected", False),
                )
            else:
                self.metrics.record(
                    MetricsCollector.EVENT,
                    request_id=request_id,
                    dependency=dependency,
                    policy=self.policy.name,
                    event=event,
                    **{k: v for k, v in fields.items() if k != "event"},
                )

        executor: PolicyExecutor[object] = PolicyExecutor(self.policy, rng, on_event=on_event)

        async def wrapped() -> object:
            try:
                return await operation()
            except OSError as exc:
                raise CallFailure(str(exc), cause=exc) from exc

        return await executor.execute(wrapped)
