"""A resilient caller that executes an operation under a resilience policy.

The operation is an arbitrary async callable (in-process for experiments, or
an HTTP call in a distributed deployment). Attempts, retries, and resilience
events are recorded as metrics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from resiliencelab.events import EventType
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
        attempt_counter: dict[str, int] = {"n": 0}

        def _context() -> dict[str, Any]:
            return attempt_context or {}

        def on_event(event: str, **fields: Any) -> None:
            if self.metrics is None:
                return
            context = _context()
            source = context.get("source_service")
            target = dependency
            if event == "attempt":
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
                attempt = fields.get("attempt")
                if fields.get("success"):
                    self.metrics.emit(
                        EventType.DEPENDENCY_COMPLETED,
                        request_id=request_id,
                        attempt=attempt,
                        source_service=source,
                        target_service=target,
                        status=fields.get("status"),
                        metadata={"duration": fields.get("duration")},
                    )
                else:
                    if fields.get("timeout"):
                        self.metrics.emit(
                            EventType.TIMEOUT_TRIGGERED,
                            request_id=request_id,
                            attempt=attempt,
                            source_service=source,
                            target_service=target,
                            reason="deadline",
                        )
                    self.metrics.emit(
                        EventType.DEPENDENCY_FAILED,
                        request_id=request_id,
                        attempt=attempt,
                        source_service=source,
                        target_service=target,
                        status=fields.get("status"),
                        reason="timeout" if fields.get("timeout") else "failed",
                        metadata={"duration": fields.get("duration")},
                    )
            elif event == "retry":
                self.metrics.emit(
                    EventType.RETRY_SCHEDULED,
                    request_id=request_id,
                    attempt=fields.get("attempt"),
                    source_service=source,
                    target_service=target,
                    status=fields.get("status"),
                    metadata={"delay": fields.get("delay")},
                )
                self.metrics.record(
                    MetricsCollector.EVENT,
                    request_id=request_id,
                    dependency=dependency,
                    policy=self.policy.name,
                    event=event,
                    **{k: v for k, v in fields.items() if k != "event"},
                )
            elif event == "timeout":
                self.metrics.emit(
                    EventType.TIMEOUT_TRIGGERED,
                    request_id=request_id,
                    attempt=None,
                    source_service=source,
                    target_service=target,
                    reason=fields.get("reason"),
                )
                self.metrics.record(
                    MetricsCollector.EVENT,
                    request_id=request_id,
                    dependency=dependency,
                    policy=self.policy.name,
                    event=event,
                    **{k: v for k, v in fields.items() if k != "event"},
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
            attempt_counter["n"] += 1
            attempt = attempt_counter["n"]
            context = _context()
            context["attempt"] = attempt
            if self.metrics is not None:
                if attempt == 1:
                    self.metrics.emit(
                        EventType.DEPENDENCY_CALLED,
                        request_id=request_id,
                        attempt=attempt,
                        source_service=context.get("source_service"),
                        target_service=dependency,
                    )
                else:
                    self.metrics.emit(
                        EventType.RETRY_EXECUTED,
                        request_id=request_id,
                        attempt=attempt,
                        source_service=context.get("source_service"),
                        target_service=dependency,
                    )
            try:
                return await operation()
            except OSError as exc:
                raise CallFailure(str(exc), cause=exc) from exc

        return await executor.execute(wrapped)
