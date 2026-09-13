"""Canonical structured event model for ResilienceLab observability.

Every meaningful runtime state change produces one typed, ordered, correlated
:class:`Event`. Events are the causal backbone for timelines, reports, and
artifact-level reproducibility. This is structured observability *inside a
simulated resilience laboratory* — not production telemetry.

Two properties of an event are deliberately distinct:

- **deterministic** fields: ``event_type``, ``sequence``, correlation IDs, and
  the seeded decisions recorded in ``metadata``;
- **wall-clock** fields: ``elapsed`` and ``timestamp`` (measurement time),
  which vary across reruns by design.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

EVENT_SCHEMA_VERSION = "1"


class EventType(str, Enum):
    EXPERIMENT_STARTED = "ExperimentStarted"
    EXPERIMENT_COMPLETED = "ExperimentCompleted"
    EXPERIMENT_FAILED = "ExperimentFailed"

    REQUEST_STARTED = "RequestStarted"
    REQUEST_COMPLETED = "RequestCompleted"
    REQUEST_FAILED = "RequestFailed"

    DEPENDENCY_CALLED = "DependencyCalled"
    DEPENDENCY_COMPLETED = "DependencyCompleted"
    DEPENDENCY_FAILED = "DependencyFailed"

    RETRY_SCHEDULED = "RetryScheduled"
    RETRY_EXECUTED = "RetryExecuted"

    TIMEOUT_TRIGGERED = "TimeoutTriggered"

    CIRCUIT_OPENED = "CircuitOpened"
    CIRCUIT_HALF_OPENED = "CircuitHalfOpened"
    CIRCUIT_CLOSED = "CircuitClosed"

    SERVICE_REQUEST_QUEUED = "ServiceRequestQueued"
    SERVICE_REQUEST_REJECTED = "ServiceRequestRejected"
    SERVICE_SATURATED = "ServiceSaturated"
    SERVICE_RECOVERED = "ServiceRecovered"

    NETWORK_DELAY_APPLIED = "NetworkDelayApplied"

    FAULT_INJECTED = "FaultInjected"
    FAULT_RECOVERED = "FaultRecovered"


@dataclass(frozen=True)
class Event:
    event_type: str
    sequence: int
    elapsed: float
    timestamp: float
    experiment_id: str
    run_id: str
    event_id: str
    request_id: int | None = None
    parent_request_id: int | None = None
    attempt: int | None = None
    service: str | None = None
    source_service: str | None = None
    target_service: str | None = None
    operation: str | None = None
    status: int | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "sequence": self.sequence,
            "elapsed": self.elapsed,
            "timestamp": self.timestamp,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "event_id": self.event_id,
            "request_id": self.request_id,
            "parent_request_id": self.parent_request_id,
            "attempt": self.attempt,
            "service": self.service,
            "source_service": self.source_service,
            "target_service": self.target_service,
            "operation": self.operation,
            "status": self.status,
            "reason": self.reason,
            "metadata": self.metadata,
        }


def event_from_dict(data: dict[str, Any]) -> Event:
    return Event(**data)


class EventEmitter:
    """Ordered, gated, thread-safe emitter of canonical events.

    ``sequence`` increments monotonically per emitter; ``elapsed`` is the
    wall-clock time from the emitter's clock, and ``timestamp`` is epoch time.
    """

    def __init__(
        self,
        experiment_id: str = "",
        run_id: str = "",
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.experiment_id = experiment_id
        self.run_id = run_id
        self._clock = clock or time.perf_counter
        self._sequence = 0
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self.recording = True

    def emit(
        self,
        event_type: EventType | str,
        *,
        request_id: int | None = None,
        parent_request_id: int | None = None,
        attempt: int | None = None,
        service: str | None = None,
        source_service: str | None = None,
        target_service: str | None = None,
        operation: str | None = None,
        status: int | None = None,
        reason: str | None = None,
        **metadata: Any,
    ) -> Event | None:
        if not self.recording:
            return None
        with self._lock:
            sequence = self._sequence
            self._sequence += 1
            event = Event(
                event_type=event_type.value if isinstance(event_type, EventType) else event_type,
                sequence=sequence,
                elapsed=self._clock(),
                timestamp=time.time(),
                experiment_id=self.experiment_id,
                run_id=self.run_id,
                event_id=f"{self.experiment_id}/{self.run_id}#{sequence}",
                request_id=request_id,
                parent_request_id=parent_request_id,
                attempt=attempt,
                service=service,
                source_service=source_service,
                target_service=target_service,
                operation=operation,
                status=status,
                reason=reason,
                metadata=dict(metadata),
            )
            self._events.append(event)
            return event

    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
