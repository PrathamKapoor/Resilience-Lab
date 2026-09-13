# Project Handoff — ResilienceLab

## 1. Current Phase

- **Vision**: evolve ResilienceLab into a 10/10 research-grade, reproducible,
  deployable resilience experimentation platform (master prompt phase list below).
- **Subphase just completed**: **Phase 2 — Controlled Simulation Improvements**
  (service processing latency, network latency/jitter, service-side capacity +
  queueing, saturation, per-service simulation metrics). Builds directly on
  Phase 1 (`1bf4ece`).
- **Status**: Phase 2 complete, uncommitted. All gates green (93 tests, ruff,
  ruff format, mypy strict). Tree has Phase 2 changes (14 modified + 5 new files).
- **Core honesty invariant**: services are deliberate in-process simulations;
  deployment targets the control plane only (see `docs/simulation.md`).

## 2. Work Completed

### Prior (commits `324ac3b`, `3af7af1`, `2a98643`, `1bf4ece`)
Core platform, hardening, multi-service topology, and Phase 1 (workload arrival
semantics + latency attribution). See `git log`.

### Phase 2 (this session, uncommitted)
- **Schema** (`core/schema.py`): new `ProcessingSpec` (constant/uniform/normal/
  lognormal/Pareto + mean/std/min/max), `CapacitySpec` (max_concurrency,
  queue_limit mirroring client-concurrency semantics), `NetworkLinkSpec`/`NetworkEdgeSpec`/
  `NetworkSpec` (default + per-edge latency/jitter), `ServiceSpec.processing`/`.capacity`,
  `SystemSpec.network`. All optional → existing configs unchanged.
- **`faults/model.py`**: added `LatencyDistribution.CONSTANT` (+ handler in `sample_latency`).
- **New simulation modules** (`services/`):
  - `capacity.py` — `ServiceCapacity` (async slot acquisition, bounded/unbounded/
    rejecting queue, wait measurement, `peak_queue_depth`, `rejected_count`,
    `snapshot()`), `ServiceSaturated` (retryable `CallFailure` status 503).
  - `processing.py` — pure seeded `sample_processing_latency(spec, rng)`.
  - `network.py` — `resolve_network_link` (edge/precedence) + `network_delay`
    (base + uniform jitter), `NETWORK_RNG_SALT`.
- **`dependency.py`**: `invoke()` now flows queue→processing→fault; accepts
  `attempt_context` to report `service_rejected`/`queue_wait`/`processing_latency`;
  emits `service_queued`/`service_rejected` events; exposes `capacity_snapshot()`;
  processing stream = `generator_for(seed, request_id, service_salt, PROCESSING_RNG_SALT)`.
- **`client.py`**: `execute(..., attempt_context=...)` attaches
  `network_latency`/`processing_latency`/`queue_wait`/`service_rejected` to each
  `downstream` row.
- **`runner.py`**: builds per-service processing/capacity, resolves network links,
  computes seeded network delay per call, collects per-service capacity snapshots
  into `RunResult.service_metrics`; closure variables bound via defaults (B023).
- **`result.py`**: `RunResult.service_metrics` + `ExperimentResult.service_metrics_per_run()`.
- **`metrics/transforms.py`**: `latency_components` now also reports `network`/
  `processing`/`queue` means.
- **`report.py`**: Measurement-semantics section reports simulated sub-components;
  new "Simulated service capacity" section (per-service capacity, peak queue,
  rejections). Fixed a `U+2212` (minus sign) that broke `console.print` on Windows
  encodings — keep CLI output ASCII.
- **`artifacts.py`**: `experiment.json` summary includes `service_metrics_per_run`.
- **Benchmarks**: new `RL-BENCH-009` (service latency), `010` (network jitter),
  `011` (capacity saturation), `012` (retry amplification under saturation);
  registered + documented. `docs/simulation.md` (new) documents the whole model.

## 3. Files Changed

Modified: `core/schema.py`, `faults/model.py`, `services/{dependency,client}.py`,
`experiments/{runner,result,report,artifacts,benchmarks}.py`,
`metrics/transforms.py`, `README.md`, `docs/{architecture,benchmarks,workloads}.md`.
New: `services/{capacity,network,processing}.py`, `docs/simulation.md`,
`benchmarks/RL-BENCH-{009..012}.yaml`, `tests/test_simulation.py`.

## 4. Simulation semantics (the important part)

- **Simulated vs wall-clock**: the experiment pipeline is wall-clock driven
  (workloads, metrics timestamps, recovery). Simulated delays are seeded
  *decisions* applied via `asyncio.sleep`; *measurement* is wall-clock.
  Documented in `docs/simulation.md`.
- **Processing**: per-request, seeded (`generator_for(seed, request_id, service_salt,
  0x7072)`); constant/uniform/normal/lognormal/pareto.
- **Network**: per-call, seeded (`generator_for(seed, request_id, 0x4E57, idx)`),
  base ± uniform jitter, floored at 0; resolved per (source,target) with `default`.
- **Queueing**: `ServiceCapacity.acquire()` returns wall-clock wait; `queue_limit`
  None/0/N → unbounded/reject/bounded; rejections raise retryable 503
  (`ServiceSaturated`), so retries amplify them (scenario F).
- **Capacity** vs **client concurrency**: service-side `capacity` (dependency
  processing slots) is explicitly separate from the client-side policy
  `concurrency` limiter.
- **Determinism**: same config + seed ⇒ same processing/network decisions; queue
  order deterministic given arrival; wall-clock completion (esp. saturation
  rejection rate) varies by host — do NOT assert exact cross-run equality.

## 5. Decisions & Gotchas

- Latency decomposition: `total = service(wall) + backoff + other(wall)`;
  `network`/`processing` (simulated) and `queue` (wall) are sub-components of
  `service`, reported separately.
- `ServiceSaturated` is retryable on purpose (models transient overload).
- Keep CLI output ASCII — `console.print` of markdown with `U+2212` raises
  `UnicodeEncodeError` under the Windows cp1252 console (`report`/`reproduce` paths).
  Do not reintroduce `−`/`–` in user-facing strings.

## 6. Testing & Verification

- `python -m pytest` → **93 passed** (14 new in `tests/test_simulation.py`:
  processing constant/normal-reproducible/uniform-bounded/none; network edge
  precedence/jitter bounds/reproducible; capacity reject/queue-wait/peak/snapshot;
  dependency processing recorded; capacity rejection recorded + raises; runner
  reflects simulated components).
- `ruff check`, `ruff format --check`, `mypy resiliencelab` (55 files) → clean.
- CLI E2E (executed): `validate` all 12 benchmarks (OK); `run` 009 (p95≈0.062,
  avail 1.0), 010 (p95≈0.046), 011 (avail 0.034, ~78k rejections), 012
  (amplification 3.02, avail 0.42); `report` RL-BENCH-011 shows processing=0.0100s +
  capacity=5/rejections; `reproduce` RL-BENCH-011; `run` RL-BENCH-001 regression
  (avail 0.902, ampl 1.20).
- Saturation availability has wall-clock variance (0.0326 vs 0.0342 across runs) —
  expected, documented.

## 7. Known Gaps (tracked, VERIFIED, not addressed this phase)

1. `POST /experiments/{id}/cancel` → 501. 2. `make reproduce-paper` → `--all`
flag doesn't exist. 3. Postgres/Redis unwired; in-memory registry. 4. No workers/
job queue. 5. No auth/quotas. 6. No dashboard. 7. Per-service *policies*
(simulation is per-service, but the resilience policy is still shared). 8.
`endpoint_mix`/`payload_size` accepted-unwired. 9. `paper/` outline only.
10. Adaptive policies not implemented.

## 8. Next Phases (master prompt order)

Phase 3 per-service policies → Phase 4 event model/observability → Phase 5
statistical/factorial → Phase 6 persistence + workers → Phase 7 cancellation →
Phase 8 API → Phase 9 dashboard → Phase 10 deploy/security → Phase 11 research
artifact/reproduce-paper → Phase 12 adaptive.

## 9. Agent Instructions

- Phase 2 is **uncommitted**; commit first (message e.g.
  `feat: add controlled service and network simulation`), gates already green.
- Preserve: in-process model, exception taxonomy, timeout contract, warmup gating,
  `await asyncio.sleep(0)` (closed-loop starvation fix), arrival model, ASCII-only
  CLI output, per-service simulation seeds.
- Do not conflate service `capacity` with client `concurrency`, and do not claim
  simulated latency equals real latency (docs/simulation.md honesty statement).