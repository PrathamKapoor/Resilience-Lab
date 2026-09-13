"""Phase 4: canonical event model, correlation, ordering, and causal traces."""

from __future__ import annotations

import json

from resiliencelab.analysis.events import causal_trace, event_summary, filter_events
from resiliencelab.core.config import parse_experiment
from resiliencelab.events import Event, EventEmitter, EventType, event_from_dict
from resiliencelab.experiments.artifacts import write_artifacts
from resiliencelab.experiments.runner import ExperimentRunner


def test_event_round_trip() -> None:
    event = Event(
        event_type="CircuitOpened",
        sequence=5,
        elapsed=1.0,
        timestamp=2.0,
        experiment_id="exp",
        run_id="run-0",
        event_id="exp/run-0#5",
        target_service="payment_service",
        metadata={"from_state": "closed", "to_state": "open"},
    )
    assert event_from_dict(event.to_dict()) == event


def test_event_schema_has_required_fields() -> None:
    event = EventEmitter("exp", "run-0").emit(EventType.REQUEST_STARTED, request_id=3)
    assert event is not None
    data = event.to_dict()
    for key in (
        "event_type",
        "sequence",
        "elapsed",
        "timestamp",
        "experiment_id",
        "run_id",
        "event_id",
    ):
        assert key in data
    assert data["event_type"] == "RequestStarted"
    assert data["request_id"] == 3


def test_emitter_sequence_and_identity() -> None:
    emitter = EventEmitter("exp", "run-0", clock=lambda: 1.0)
    first = emitter.emit(EventType.REQUEST_STARTED, request_id=1)
    second = emitter.emit(EventType.REQUEST_COMPLETED, request_id=1)
    assert first is not None and second is not None
    assert first.sequence == 0
    assert second.sequence == 1
    assert first.event_id == "exp/run-0#0"
    assert first.elapsed == 1.0
    assert first.experiment_id == "exp" and first.run_id == "run-0"


def test_emitter_recording_gate() -> None:
    emitter = EventEmitter("exp", "run-0")
    emitter.recording = False
    assert emitter.emit(EventType.REQUEST_STARTED) is None
    assert len(emitter) == 0
    emitter.recording = True
    assert emitter.emit(EventType.REQUEST_STARTED) is not None
    assert len(emitter) == 1


def test_filter_events() -> None:
    emitter = EventEmitter("exp", "run-0")
    emitter.emit(EventType.REQUEST_STARTED, request_id=1)
    emitter.emit(EventType.CIRCUIT_OPENED, target_service="payment_service")
    emitter.emit(EventType.CIRCUIT_OPENED, target_service="inventory_service")
    events = emitter.events()
    assert len(filter_events(events, event_type=EventType.CIRCUIT_OPENED)) == 2
    assert len(filter_events(events, service="payment_service")) == 1
    assert len(filter_events(events, request_id=1)) == 1


def test_event_summary_and_causal_trace() -> None:
    emitter = EventEmitter("exp", "run-0", clock=lambda: 0.0)
    emitter.emit(EventType.REQUEST_STARTED, request_id=1)
    emitter.emit(EventType.DEPENDENCY_CALLED, request_id=1)
    emitter.emit(EventType.REQUEST_FAILED, request_id=1)
    summary = event_summary(emitter.events())
    assert summary["RequestStarted"] == 1
    assert "req=1" in causal_trace(emitter.events())


def _causal_config() -> dict:
    return parse_experiment(
        {
            "experiment": {
                "id": "ev_causal",
                "name": "causal trace",
                "version": 1,
                "system": {"services": [{"name": "payment_service"}]},
                "workload": {
                    "type": "closed_loop",
                    "clients": 1,
                    "duration": "0.2s",
                    "warmup": "0s",
                },
                "failure": [
                    {
                        "target": "payment_service",
                        "type": "http_503",
                        "mode": "constant",
                        "probability": 1.0,
                    }
                ],
                "policy": {
                    "retry": {"enabled": True, "max_attempts": 2},
                    "backoff": {"type": "fixed", "base": "0.001s", "maximum": "0.001s"},
                    "circuit_breaker": {"enabled": True, "threshold": 1},
                },
                "repetitions": {"count": 1, "seed_strategy": "deterministic", "base_seed": 3},
            }
        }
    )


def test_sequence_is_monotonic() -> None:
    events = ExperimentRunner().run(_causal_config()).runs[0].events
    sequences = [e.sequence for e in events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)


def test_causal_retry_trace_reconstructable() -> None:
    events = ExperimentRunner().run(_causal_config()).runs[0].events
    by_request: dict[int, list[str]] = {}
    for event in events:
        if event.request_id is not None:
            by_request.setdefault(event.request_id, []).append(event.event_type)
    request_id = next(rid for rid, kinds in by_request.items() if "RetryScheduled" in kinds)
    kinds = by_request[request_id]
    assert kinds.index("DependencyCalled") < kinds.index("DependencyFailed")
    assert kinds.index("DependencyFailed") < kinds.index("RetryScheduled")
    assert kinds.index("RetryScheduled") < kinds.index("RetryExecuted")


def test_circuit_opened_event_attributed_to_service() -> None:
    events = ExperimentRunner().run(_causal_config()).runs[0].events
    opened = {e.target_service for e in events if e.event_type == "CircuitOpened"}
    assert opened == {"payment_service"}


def test_events_persisted_and_hashed(tmp_path) -> None:
    result = ExperimentRunner().run(_causal_config())
    write_artifacts(result, tmp_path)
    assert (tmp_path / "raw" / "events-0.jsonl").exists()
    assert (tmp_path / "raw" / "events-experiment.jsonl").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["event_schema_version"] == "1"
    assert manifest["event_count"] > 0
    assert "events_hash" in manifest
    assert (tmp_path / "raw" / "events-hash.txt").exists()
