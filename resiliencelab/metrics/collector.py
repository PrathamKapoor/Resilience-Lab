"""Metrics collector: a structured, thread-safe event/observation sink."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from resiliencelab.events import Event, EventEmitter, EventType

Clock = Callable[[], float]

Record = dict[str, Any]


class MetricsCollector:
    REQUEST = "request"
    DOWNSTREAM = "downstream"
    EVENT = "event"

    def __init__(
        self,
        experiment_id: str = "",
        run_id: str = "",
        seed: int | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.experiment_id = experiment_id
        self.run_id = run_id
        self.seed = seed
        self._clock = clock or time.perf_counter
        self._records: list[Record] = []
        self._lock = threading.Lock()
        self._recording = True
        self._emitter = EventEmitter(experiment_id, run_id, clock=self._clock)

    @property
    def recording(self) -> bool:
        return self._recording

    def set_recording(self, value: bool) -> None:
        self._recording = value
        self._emitter.recording = value

    def set_context(self, experiment_id: str, run_id: str, seed: int | None) -> None:
        self.experiment_id = experiment_id
        self.run_id = run_id
        self.seed = seed

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
        return self._emitter.emit(
            event_type,
            request_id=request_id,
            parent_request_id=parent_request_id,
            attempt=attempt,
            service=service,
            source_service=source_service,
            target_service=target_service,
            operation=operation,
            status=status,
            reason=reason,
            **metadata,
        )

    def events(self) -> list[Event]:
        return self._emitter.events()

    def record(self, kind: str, **fields: object) -> None:
        if not self._recording:
            return
        row = {
            "kind": kind,
            "t": self._clock(),
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "seed": self.seed,
            **fields,
        }
        with self._lock:
            self._records.append(row)

    def extend(self, rows: list[Record]) -> None:
        with self._lock:
            self._records.extend(rows)

    def records(self) -> list[Record]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)
