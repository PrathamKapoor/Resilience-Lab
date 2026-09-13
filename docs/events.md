# Event model & observability

> This is **structured observability inside a simulated resilience
> laboratory**, not production telemetry from real distributed services.

Every meaningful runtime state change produces one canonical, typed, ordered,
correlated `Event` (`resiliencelab/events.py`). The event stream is the causal
backbone for timelines, reports, artifact reproducibility, and future UI.

## Event identity & correlation

Each event carries:

- `event_id` — stable per-run identifier (`{experiment_id}/{run_id}#{sequence}`)
- `event_type` — one of the canonical `EventType` values
- `sequence` — monotonic per-run ordering
- `elapsed` / `timestamp` — wall-clock times
- `experiment_id`, `run_id`
- `request_id`, `parent_request_id`, `attempt`
- `service`, `source_service`, `target_service`
- `operation`, `status`, `reason`
- `metadata` — typed, structured extras

## Ordering semantics

- `sequence` increments monotonically per run and is the primary ordering key.
- `elapsed` is the wall-clock time from the run clock (varies across reruns).
- `timestamp` is epoch wall-clock time.
- Deterministic causal decisions (seeded fault outcomes, retry decisions,
  breaker transitions) are reproducible; timestamps/elapsed are not.

## Taxonomy

| Category | Events |
|---|---|
| Experiment | `ExperimentStarted`, `ExperimentCompleted`, `ExperimentFailed` |
| Request | `RequestStarted`, `RequestCompleted`, `RequestFailed` |
| Dependency | `DependencyCalled`, `DependencyCompleted`, `DependencyFailed` |
| Retry | `RetryScheduled`, `RetryExecuted` |
| Timeout | `TimeoutTriggered` |
| Circuit breaker | `CircuitOpened`, `CircuitHalfOpened`, `CircuitClosed` |
| Capacity/queue | `ServiceRequestQueued`, `ServiceRequestRejected`, `ServiceSaturated`, `ServiceRecovered` |
| Network | `NetworkDelayApplied` |
| Faults | `FaultInjected`, `FaultRecovered` |

A logical dependency request with one retry produces, in order:

```text
DependencyCalled   attempt=1
DependencyFailed   attempt=1
RetryScheduled     attempt=2
RetryExecuted      attempt=2
DependencyCompleted attempt=2
```

## Example trace

```text
 0.000  ExperimentStarted
 0.102  RequestStarted          req=10
 0.104  DependencyCalled        req=10 → payment_service attempt=1
 0.115  FaultInjected           req=10 (http_503)
 0.116  DependencyFailed        req=10 → payment_service attempt=1
 0.116  RetryScheduled          req=10 attempt=2
 0.125  RetryExecuted           req=10 → payment_service attempt=2
 0.130  CircuitOpened           → payment_service
 0.132  RequestFailed           req=10
```

## Retrieval

- CLI: `resiliencelab events <experiment> [--type CircuitOpened] [--service payment_service] [--request N] [--trace]`
- API: `GET /api/v1/experiments/{id}/events?event_type=...&service=...&request_id=...`
- Artifacts: `raw/events-<run>.jsonl` + `raw/events-experiment.jsonl`, hashed and
  referenced in `manifest.json` (`events_hash`, `event_schema_version`, `event_count`).

## Event → metric relationship

Events are canonical observations; the flat `request`/`downstream`/`event`
record stream used by existing metrics remains the source for aggregate
scores, but its key counters (retries, breaker transitions, capacity
rejections) correspond directly to `RetryExecuted`, `CircuitOpened`, and
`ServiceRequestRejected` events. Latency component fields (`network`,
`processing`, `queue`, `retry`, `total`) remain explicitly recorded because
wall-clock component times cannot always be reconstructed from event
timestamps alone — this limitation is deliberate and documented.