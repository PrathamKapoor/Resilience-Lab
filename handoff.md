# Project Handoff — ResilienceLab

## 1. Current Phase

- **Vision**: 10/10 research-grade resilience experimentation platform (master-prompt phases below).
- **Subphase just completed**: **Phase 4 — First-Class Event Model + Observability** (canonical typed events, correlation/ordering, runtime instrumentation, artifacts, observability summary + causal trace, CLI/API access, benchmarks 015/016).
- **Status**: complete, uncommitted. Gates green (116 tests, ruff, format, mypy strict). Builds on `a7dca18`.
- **Honesty invariant**: structured observability of an in-process simulation — not production telemetry.

## 2. Work Completed

### Prior (commits through `a7dca18`)
Core, hardening, topology, Phase 1 (workload/latency), Phase 2 (simulation), Phase 3 (per-service policies). See `git log`.

### Phase 4 (this session, uncommitted)
- **Event model** (`events.py`, NEW): `EVENT_SCHEMA_VERSION="1"`; `EventType` enum (experiment/request/dependency/retry/timeout/breaker/capacity/network/fault); frozen `Event` dataclass (`event_type, sequence, elapsed, timestamp, experiment_id, run_id, event_id, request_id, parent_request_id, attempt, service, source_service, target_service, operation, status, reason, metadata`); `EventEmitter` (monotonic sequence, gated, wall-clock `elapsed`/`timestamp`); `event_from_dict`.
- **Emitter integration** (`metrics/collector.py`): `MetricsCollector` composes an `EventEmitter`; `emit()`/`events()`/`set_recording` gating (warmup excluded).
- **Instrumentation**:
  - `workloads/generator.py` — `RequestStarted/Completed/Failed`.
  - `services/client.py` — `DependencyCalled/Completed/Failed`, `RetryScheduled`, `RetryExecuted` (attempt counter in the operation wrapper), `TimeoutTriggered`.
  - `resilience/policy.py` — emits `timeout` (reason deadline/read_timeout) at the previously-silent deadline paths.
  - `services/dependency.py` — `ServiceRequestQueued/Rejected`, `ServiceSaturated/Recovered`, `FaultInjected/Recovered`.
  - `experiments/runner.py` — `CircuitOpened/HalfOpened/Closed`, `NetworkDelayApplied`, experiment lifecycle via a dedicated `EventEmitter`.
- **Result** (`result.py`): `RunResult.events`, `ExperimentResult.events` + `run_events()`.
- **Artifacts** (`artifacts.py`): `raw/events-<run>.jsonl` + `raw/events-experiment.jsonl` + `raw/events-hash.txt`; manifest gains `events_hash`, `event_schema_version`, `event_count`.
- **Analysis** (`analysis/events.py`, NEW): `filter_events`, `event_summary`, `causal_trace` (ordered by `elapsed`, `sequence` tiebreak).
- **Report** (`report.py`): "Observability summary" + "Causal timeline (sample)".
- **CLI** (`cli/app.py`): `events` command (`--type/--service/--request/--trace/--limit`), read-only from `raw/events-*.jsonl`.
- **API** (`api/app.py`): `GET /experiments/{id}/events` with optional filters.
- **Benchmarks**: RL-BENCH-015 (retry causal trace), RL-BENCH-016 (saturation/recovery trace); registered + documented.
- **Docs**: `docs/events.md` (NEW) + README/architecture updates.

## 3. Files Changed (uncommitted)

Modified: `metrics/collector.py`, `resilience/policy.py`, `workloads/generator.py`, `services/{client,dependency}.py`, `experiments/{runner,result,artifacts,report,benchmarks}.py`, `cli/app.py`, `api/app.py`, `README.md`, `docs/{architecture,benchmarks}.md`.
New: `resiliencelab/events.py`, `resiliencelab/analysis/events.py`, `docs/events.md`, `benchmarks/RL-BENCH-{015,016}.yaml`, `tests/test_events.py`.

## 4. Event semantics (hard rules to preserve)

- **Ordering**: `sequence` monotonic per run (deterministic); `elapsed`/`timestamp` wall-clock (vary across reruns). `causal_trace` sorts by `(elapsed, sequence)` — correct when mixing experiment-lifecycle and run events.
- **Correlation**: request-level events carry `request_id`/`attempt`; dependency events carry `source_service`/`target_service`; `attempt_context` (dict) threads `source_service`/`target_service`/simulation sub-latencies per attempt. Breaker transitions are service-level (no `request_id` — by design, cross-request).
- **Deterministic vs wall-clock**: fault outcomes/retry decisions/breaker transitions are seeded-deterministic; timestamps/elapsed/queue wait are wall-clock.
- **Warmup gating**: `emit()` is gated by `recording` exactly like metric records — warmup produces no events.
- **Event → metrics**: existing `request/downstream/event` records remain the metric source; the key counters correspond to `RetryExecuted`/`CircuitOpened`/`ServiceRequestRejected` events.

## 5. Decisions & Gotchas

- `MetricsCollector` is the single sink threaded everywhere; the `EventEmitter` is composed inside it (no parallel bus).
- Retry `RetryScheduled` (from policy `retry` event) vs `RetryExecuted` (from the client's per-attempt operation wrapper) are distinct — required by §8 causality.
- The previously-silent deadline-exceeded paths in `policy.py` now emit `timeout` (they previously raised without any observation).
- Note found during verification: RL-BENCH-015's `FaultInjected` count is LOW because an aggressive breaker opens almost immediately and sheds the faulting dependency (correct behavior, not a bug). Event coherence verified via a constant-fault smoke: `DependencyFailed == FaultInjected == 666`.
- `Client.on_event` uses `**fields: Any` (mypy-typed; values flow to typed `emit`).

## 6. Testing & Verification

- `python -m pytest` → **116 passed** (10 new in `tests/test_events.py`: round-trip, required fields, sequence/identity, recording gate, filter, summary/causal trace, monotonic sequence, causal retry trace, breaker attribution, event persistence/hash).
- `ruff check`, `ruff format --check`, `mypy resiliencelab` (58 files) → clean.
- `validate` all 16 benchmarks OK. `run` RL-BENCH-015/016; `events --trace/--type` shows reconstructable retries/breaker/saturation; `reproduce` works; manifest carries `events_hash`/`event_schema_version`/`event_count`; report renders "Observability summary" + causal timeline.

## 7. Known Gaps (unchanged, tracked)

cancel 501; `make reproduce-paper` → `--all` missing; Postgres/Redis unwired (in-memory registry); no workers; no auth/quotas; no dashboard; `endpoint_mix`/`payload_size` unwired; `paper/` outline only; adaptive policies not implemented. (Event model is the foundation the dashboard/paper will consume.)

## 8. Next Phases (master prompt order)

Phase 5 statistical/factorial → Phase 6 persistence+workers → Phase 7 cancellation → Phase 8 API productionization → Phase 9 dashboard (consume events) → Phase 10 deploy/security → Phase 11 research artifact/reproduce-paper → Phase 12 adaptive.

## 9. Agent Instructions

- Phase 4 uncommitted; commit first (`feat: add first-class experiment event model`), gates green.
- Preserve: in-process model, exception taxonomy, timeout contract, warmup gating, arrival model, per-service policy isolation, fan-out short-circuit, event ordering semantics (`elapsed, sequence`), ASCII-only CLI output.
- Do not add an external telemetry/event bus; keep the in-process emitter composed in `MetricsCollector`.