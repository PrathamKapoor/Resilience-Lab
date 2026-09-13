# Project Handoff — ResilienceLab

## 1. Current Phase

- **Vision** (all phases): evolve ResilienceLab into a 10/10 research-grade, reproducible, deployable resilience experimentation platform. See the master prompt's phase list below.
- **Subphase just completed**: **Phase 1 — Scientific correctness** (workload arrival semantics + latency measurement attribution + metric definitions). This was the highest-impact correctness gap per the master prompt (it said: "The system must never silently claim to execute a workload type that it does not actually implement").
- **Overall objective**: a reproducible simulated resilience laboratory for experimentally evaluating resilience policies under controlled workloads/failures. In-process fake services are a deliberate methodological choice; deployment targets the *control plane*, not the simulated services.
- **Status**: Phase 1 **complete**. Tree has uncommitted Phase 1 changes (8 files). All gates green (79 tests, ruff, ruff format, mypy strict).

## 2. Work Completed

### Prior subphases (commits `324ac3b`, `3af7af1`, `2a98643`) — unchanged
Core platform (resilience engine, faults, schema, services, workloads, metrics, analysis, runner, artifacts, CLI, REST API, benchmarks), hardening (warmup-gated metrics, starvation yield, in-process execution, BackgroundTasks API, non-finite stats), and multi-service topology (service graph, per-target routing, cascade fan-out). See `git log`.

### Phase 1 — Scientific correctness (this session, uncommitted)
- **Workload arrival model** (`workloads/arrivals.py`, NEW): `ArrivalModel.gap(elapsed, rng)` computes inter-arrival gaps as a pure, seeded function of elapsed time. Implemented distinct semantics for all 7 `WorkloadType`s (closed_loop has no arrival model and raises). Fixed the previous bug where `burst`/`periodic`/`random` silently behaved as closed-loop.
  - `constant_rate`: fixed `1/rate`; `open_loop`: exponential (poisson/exponential dist) or fixed (constant dist); `random`: Uniform(0, 2/rate); `burst`: `burst_size` fast gaps then `burst_interval` idle; `periodic`: sinusoidal rate with `period`/`burstiness`; `ramp`: linear 10%→full over `duration`.
- **Generator refactor** (`workloads/generator.py`): `_drive` now dispatches closed_loop → `_closed_loop` (unchanged, starvation fix intact) and everything else → `_arrival_loop` (single loop consuming `ArrivalModel.gap`). Removed the old `_open_loop`/`_ramp`/`_next_gap` and the silent fallthrough.
- **Schema** (`core/schema.py`): added backward-compatible `WorkloadSpec` fields `burst_size` (default 10), `burst_interval` (1s), `period` (1s).
- **Latency measurement semantics** (`metrics/transforms.py`): new `latency_components(records)` decomposes mean request latency into `total` / `service` (Σ per-attempt downstream latency) / `retry` (Σ retry-event delays) / `other` (queue + timeout + scheduling residual). Report (`experiments/report.py`) now emits a "Measurement semantics" section with these numbers plus explicit units/definitions.
- **Tests** (`tests/test_workloads.py`, NEW — 12 tests): deterministic proofs that each mode produces distinct traffic (fixed vs stochastic vs burst pattern vs oscillation vs ramp), stochastic reproducibility, and latency decomposition correctness.
- **Docs**: `docs/workloads.md` (NEW) documenting mode semantics, fields, and latency attribution; `docs/architecture.md` pointer added.

## 3. Files Changed (uncommitted)

- `resiliencelab/workloads/arrivals.py` (NEW), `resiliencelab/workloads/generator.py`
- `resiliencelab/core/schema.py`, `resiliencelab/metrics/transforms.py`, `resiliencelab/experiments/report.py`
- `tests/test_workloads.py` (NEW), `docs/workloads.md` (NEW), `docs/architecture.md`
- Verify with `git status --short`, `git diff --stat`.

## 4. Architecture / State (VERIFIED)

- **Execution model**: fully in-process. `ExperimentRunner.run_async` → per seed: fresh `Clock`, `MetricsCollector`, `ResiliencePolicy`, N `DependencyService`s (per graph node), one shared `ResilientClient`, `SystemUnderTest`, `WorkloadGenerator`. SUT fans out over dependencies in topological order, short-circuiting on first failure. No HTTP in hot path.
- **Workloads**: `WorkloadGenerator.run` gates warmup via `MetricsCollector.set_recording`; closed-loop saturates against a `send` coroutine; all other modes drive an `ArrivalModel` gap sequence with `generator_for(seed, 200_000)`.
- **Metrics flow**: `PolicyExecutor` emits `attempt`/`retry`/`rejected`; `ResilientClient` records `downstream` (per attempt, with `latency` = attempt duration) and `event` rows; workload records `request` rows (`latency` = total). Latency decomposition relies on `request_id` correlation across the three record kinds.
- **Config**: `pyproject.toml` — ruff `E,F,I,N,UP,B,SIM,C4,ASYNC`, ignores `E501,B008,SIM108,C901,UP042,N818`; mypy strict `python_version=3.12`; pytest `asyncio_mode=auto`. Python 3.13.14, package installed editable `[dev,parquet]`.

## 5. Decisions Made (all still hold)

- In-process execution (nested-ASGI deadlock finding); `str, Enum`; `CallFailure` name; `Rng` protocol; timeout-vs-`DeadlineExceeded` contract; `recovery_time=inf` honesty; mypy target 3.12.
- **Phase 1**: arrival gaps made *pure and seeded*; stochastic reproducibility asserted on the gap functions, never on wall-clock counts/timings. `closed_loop` explicitly has no arrival model.
- Latency decomposition is **derived post-hoc** from existing records (no hot-path change), documented honestly; "other" includes timeout/queue/scheduling residual.

## 6. Requirements & Constraints

- Preserve: warmup exclusion from ALL metric kinds; per-request seeded determinism (service-0 salt = `FAULT_RNG_SALT`); `max_attempts` = total attempts; amplification definition; `recovery_time=inf`; strict mypy + ruff + format clean (`make check`); no `python -m resiliencelab.cli.app` (use `resiliencelab` or `python -m resiliencelab`).
- Do not add code comments unless asked; type hints + naming instead.
- Do NOT misrepresent the in-process fake services as real microservices; simulation is deliberate.
- Do not assert wall-clock equality in tests (duration-based runs vary); assert on seeded RNG behavior or single-run invariants.

## 7. Testing & Verification

- `python -m pytest` → **79 passed** (was 67; +12 workload/latency tests).
- `ruff check`, `ruff format --check`, `mypy resiliencelab` (strict, 52 files) → clean.
- CLI smoke (actually executed): `run` open_loop (availability 1.0, throughput 58.8) and `run` burst (availability 1.0) — both complete and produce artifact bundles.
- Not verified: Docker/K8s, Postgres/Redis (unwired — known gap), full paper reproduction, per-service policies, non-closed-loop benchmark configs (all 8 benchmarks remain `closed_loop`).

## 8. Known Gaps (from master-prompt audit — VERIFIED)

1. `POST /experiments/{id}/cancel` → HTTP 501 (`api/app.py`).
2. `make reproduce-paper` → `reproduce --all`, but no `--all` flag (broken).
3. Postgres/Redis provisioned in compose but **unwired**; registry in-memory.
4. No worker/job execution architecture; no auth/quotas.
5. No dashboard UI.
6. Policies shared across services (no per-service policy isolation).
7. `endpoint_mix` / `payload_size` accepted but unwired.
8. `paper/` outline only, not an executable research artifact.
9. Adaptive policy (RL/bandits) documented but not implemented.

## 9. Next Phases (per master prompt, in order)

- **Phase 2 — Simulation model**: service processing latency, network latency/jitter, connection failures, queueing, service/dependency saturation, resource constraints (all controlled + documented).
- **Phase 3 — Per-service policies**: `policy.<service>` overrides; add policy-isolation tests; keep backward compat.
- **Phase 4 — Event model**: first-class structured `ExperimentStarted/RequestStarted/RetryScheduled/CircuitOpened/...` events with correlation context driving timelines/analysis.
- **Phase 5 — Statistical/factorial upgrades** (interaction analysis, Pareto frontier, multiple comparisons).
- **Phase 6 — Persistence + job queue/workers** (Postgres migrations, Redis/RQ or Celery).
- **Phase 7 — Cancellation + lifecycle.** **Phase 8 — API productionization.** **Phase 9 — Dashboard.** **Phase 10 — Deployment/security/quotas.** **Phase 11 — Research artifact + `reproduce-paper`.** **Phase 12 — Adaptive policies.**

Before starting any phase: run `make check`, read the relevant module, keep all three gates green after each change.

## 10. Critical Context (bugs/decisions that shaped the code — do not regress)

- `await asyncio.sleep(0)` in `workloads/generator.py:_closed_loop` prevents event-loop starvation on fully-synchronous call chains — do not remove.
- Warmup gating via `MetricsCollector.recording` — do not bypass; warmup writes no request/downstream rows.
- Nested `httpx.ASGITransport` deadlocks → no HTTP in experiment path.
- starlette ≥0.52 `TestClient` doesn't run `asyncio.create_task` fire-and-forget → API `/run` uses `BackgroundTasks`; `Runtime.submit` is the production path.
- Never name scratch files after stdlib modules (`inspect.py` incident); scratch lives in `%TEMP%\opencode`.
- PowerShell `Select-Object` truncates/wraps long lines — verify suspicious output against the file.
- Git identity: `ResilienceLab <resiliencelab@example.com>`; no remote.

## 11. Agent Instructions

- Phase 1 changes are **uncommitted**; commit them first (green, message e.g. "Phase 1: workload arrival semantics + latency attribution"), then continue with Phase 2.
- Do not rewrite the in-process execution model, exception taxonomy, timeout contract, metrics-gating, or the arrival model without understanding §5/§10.
- Preserve the invariant "same seed + same config ⇒ reproducible stochastic decisions" while "wall-clock completion varies".