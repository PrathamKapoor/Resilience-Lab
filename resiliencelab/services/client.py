"""A resilient caller that executes an operation under a resilience policy.

The operation is an arbitrary async callable (in-process for experiments, or
an HTTP call in a distributed deployment). Attempts, retries, and resilience
events are recorded as metrics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

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
    ) -> object:
        last_status: dict[str, int | None] = {"status": None}

        def on_event(event: str, **fields: object) -> None:
            if self.metrics is None:
                return
            if event == "attempt":
                self.metrics.record(
                    MetricsCollector.DOWNSTREAM,
                    request_id=request_id,
                    dependency=dependency,
                    attempt=fields.get("attempt"),
                    success=fields.get("success"),
                    timeout=fields.get("timeout"),
                    status=fields.get("status")
                    if fields.get("status") is not None
                    else last_status["status"],
                    latency=fields.get("duration"),
                )
            else:
                self.metrics.record(
                    MetricsCollector.EVENT,
                    request_id=request_id,
                    dependency=dependency,
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
