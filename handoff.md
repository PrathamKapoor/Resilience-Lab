# Project Handoff — ResilienceLab

## 1. Current Phase

- **Vision**: 10/10 research-grade resilience experimentation platform (master-prompt phase list below).
- **Subphase just completed**: **Phase 3 — Per-Service Resilience Policies** (policy scoping, resolution, runtime isolation, service-aware metrics, provenance, report, benchmarks 013/014).
- **Status**: complete, uncommitted. Gates green (106 tests, ruff, format, mypy strict). Builds on `0f35373`.
- **Honesty invariant**: in-process simulation; deployment targets the control plane only.

## 2. Work Completed

### Prior (commits through `0f35373`)
Core platform, hardening, topology, Phase 1 (workload/latency semantics), Phase 2 (simulation). See `git log`.

### Phase 3 (this session, uncommitted)
- **Schema** (`core/schema.py`): `ExperimentSpec.policies: dict[str, dict[str, Any]]` (raw per-service overrides); `POLICY_SCHEMA_VERSION = "1"`; `merge_policy_dicts()` (recursive override merge). Validator: override keys must reference declared services (when `services` present) and each override deep-merge-validates against the default policy (so `validate` catches bad policies).
- **Resolution** (`core/policies.py`, NEW): `PolicyResolver.resolve(service_name)` → concrete `PolicySpec` (default deep-merged with override); `resolved()`/`effective()`; `service_names(spec)` helper. Config vs runtime state separated: `build_policy` creates fresh `CircuitBreaker`/`ConcurrencyLimiter`/`Retry` per service.
- **Runner** (`experiments/runner.py`): builds one runtime policy + one `ResilientClient` per service; per-service circuit-breaker transition listener records `dependency` on the event. Replaced the single shared policy/client.
- **Metrics** (`services/client.py`): `downstream`/`event` records now carry `policy=<resolved policy name>`, so behavior is attributable per service.
- **Report** (`experiments/report.py`): "Service policies" section listing the effective policy per service; distinguishes configured vs resolved.
- **Provenance** (`experiments/artifacts.py`): `experiment.json` gains `policies{default, overrides, resolved, schema_version}`.
- **Docs**: `docs/policies.md` (NEW) + architecture/README/benchmarks updates.

## 3. Files Changed (uncommitted)

Modified: `core/schema.py`, `experiments/{runner,report,artifacts,benchmarks}.py`, `services/client.py`, `README.md`, `docs/{architecture,benchmarks}.md`.
New: `core/policies.py`, `docs/policies.md`, `benchmarks/RL-BENCH-{013,014}.yaml`, `tests/test_policies.py`.

## 4. Policy semantics (hard rules to preserve)

- **Scope**: destination-service. `per-service override → default → schema defaults`.
- **Inheritance**: recursive merge; dict values merge, others (incl. `None`) replace. `retry: null`/`retry:{enabled:false}` disables retry.
- **Isolation**: each service's policy is built into independent runtime state (breaker/concurrency/retry). No shared mutable executor.
- **Determinism**: resolution deterministic; persisted in artifacts + report.
- **Backward compat**: `policy` only (no `policies`) → identical behavior; legacy single `payment_service` resolves to the global policy.

## 5. Decisions & Gotchas

- Fan-out still **short-circuits on first failing service** (topology-phase cascade semantics). Integration tests use single-failure or no-failure configs to avoid the first failure masking later services. Do NOT change the fan-out semantics.
- Warmup swallows breaker transitions/attempts (collector gate). Breaker/failure integration tests use `warmup: 0`. Benchmarks keep warmup and add `failure.start` implicitly via runner (`start + warmup`).
- Circuit breaker is only checked at request entry (`cb.allow()` before the retry loop), not per retry attempt — pre-existing design; do not change.
- Service-side `ServiceSaturated` (capacity reject) is retryable, so saturation + retry can keep a low-threshold breaker open with near-zero availability — tune benchmark breaker thresholds/recovery to avoid degenerate results.
- Predicate-typed config keys: `policy` (global) + `policies` (overrides) — NOT a `resilience:` block (adapted to repo conventions).

## 6. Testing & Verification

- `python -m pytest` → **106 passed** (13 new in `tests/test_policies.py`: resolver default/single/partial/disable, independent executors, breaker/concurrency/retry/timeout isolation, cross-service retry leakage + reversal, breaker attribution, capacity+policy isolation, policy attribution).
- `ruff check`, `ruff format --check`, `mypy resiliencelab` (56 files) → clean.
- `validate` all 14 benchmarks OK; `run` RL-BENCH-013 (avail 0.24, ampl 2.51) + RL-BENCH-014 (avail 0.16, ampl 0.32, breaker sheds) → report shows per-service policies; artifacts `policies.resolved` correct.

## 7. Known Gaps (unchanged, tracked)

cancel 501; `make reproduce-paper` → `--all` missing; Postgres/Redis unwired (in-memory registry); no workers; no auth/quotas; no dashboard; `endpoint_mix`/`payload_size` unwired; `paper/` outline only; adaptive policies not implemented.

## 8. Next Phases (master prompt order)

Phase 4 event model/observability → Phase 5 statistical/factorial → Phase 6 persistence+workers → Phase 7 cancellation → Phase 8 API → Phase 9 dashboard → Phase 10 deploy/security → Phase 11 research artifact/reproduce-paper → Phase 12 adaptive.

## 9. Agent Instructions

- Phase 3 uncommitted; commit first (`feat: add per-service resilience policy isolation`), gates green.
- Preserve: in-process model, exception taxonomy, timeout contract, warmup gating, `await asyncio.sleep(0)`, arrival model, simulation seeds, fan-out short-circuit, `max_attempts`=total attempts, per-service salt `FAULT_RNG_SALT+index`.
- Do not reintroduce a single shared policy/client; do not change fan-out; keep CLI output ASCII (no `−`/`–`).