# Project Handoff — ResilienceLab

## 1. Current Phase

- **Phase**: Greenfield build (Phase 1 of the larger ResilienceLab vision: experimental core → resilience engine → fault lab → topology → observability → statistics → product → reproducibility → adaptive → deployment → research campaign).
- **Subphase just completed**: Multi-service topology (handoff §10 Option A). Extended `ExperimentSpec.system` with a service graph, per-target fault routing, N-dependency fan-out with cascade short-circuiting, topology in reports/artifacts, RL-BENCH-006 as a true two-service cascade, 8 new tests.
- **Overall objective**: A reproducible fault-injection and resilience-benchmarking platform for distributed services, suitable for deployment, hackathon demo, and a research paper.
- **Status**: Subphase **complete**. Working tree has the topology changes uncommitted (8 files, +255/−17); all quality gates green (67 tests, ruff, ruff format, mypy strict).

## 2. Work Completed

### Prior work (commits `324ac3b`, `3af7af1`) — unchanged, see git log
Core platform (resilience engine, fault injection, schema, services, workloads, metrics, analysis, runner, artifacts, CLI, REST API, benchmarks) plus hardening (warmup-gated metrics, starvation yield, in-process execution, BackgroundTasks API, non-finite stats guards, strict typing). Details in previous handoff version (git show `1c782de:handoff.md` if needed).

### Multi-service topology (this session, uncommitted)
- **Service graph schema** (`core/schema.py`): new `ServiceSpec` (`name`, `depends_on`); `SystemSpec.services` (default `[]` = legacy single-service mode); graph validator (unique names, known deps, no self-deps, cycle detection); `SystemSpec.call_order()` topological order (stable, declared-order tiebreak); `ExperimentSpec` validator requiring `failure.target` to match a declared service when `services` is non-empty. Legacy configs with arbitrary targets still validate when `services` is empty.
- **Per-service fault streams** (`services/dependency.py`): new `salt` param (default `FAULT_RNG_SALT`, so single-service determinism is byte-identical); `invoke()` uses `generator_for(seed, request_id, self.salt)`.
- **Runner fan-out** (`experiments/runner.py`): `_injectors_by_service()` groups injectors by `FailureSpec.target` in graph mode, legacy single-key mode otherwise; `_service_names()` returns `call_order()` or `["payment_service"]`; `_run_once` builds one `DependencyService` per service (salt offset by index) and the SUT `downstream` calls them sequentially in call order, short-circuiting on first failure (upstream outage cascades by sparing downstream calls). Single shared `ResilientClient`/policy across services.
- **Report/artifacts**: `report.build_report` Configuration block gains a `services:` line (names + `depends_on`); `artifacts.write_artifacts` `experiment.json` summary gains additive `topology: [{name, depends_on}]`. `configuration.yaml` already carried `system.services`.
- **RL-BENCH-006** now declares `system.services: [payment_service, inventory_service(depends_on=payment_service)]`; its two staged faults hit distinct services. Other benchmarks unchanged (legacy mode).
- **Tests** (8 new): `test_schema.py` — graph accepted + ordered, unknown target rejected, legacy arbitrary target accepted, duplicates/unknown-dep/cycle rejected; `test_integration.py` — two-service cascade (availability 0, both services touched), fault routing isolation (payment all-success, inventory all-failed).
- **Docs**: `docs/architecture.md` topology paragraph.
- **E2E verified**: `validate` + `run` (1 rep: availability 0.2732) + `report` on RL-BENCH-006; report shows the topology block.

## 3. Files Changed

Uncommitted topology work (verify with `git status --short`, `git diff --stat`):

- `resiliencelab/core/schema.py` — `ServiceSpec`, `SystemSpec.services` + `_check_graph` + `call_order`, `ExperimentSpec` target validator (+62).
- `resiliencelab/services/dependency.py` — `salt` param (+4/−2).
- `resiliencelab/experiments/runner.py` — `_service_names`, `_injectors_by_service`, N-service `_run_once` (+57/−17); old `_injectors` removed.
- `resiliencelab/experiments/report.py` — `_topology_line` + config line (+12).
- `resiliencelab/experiments/artifacts.py` — `topology` in `experiment.json` summary (+4).
- `benchmarks/RL-BENCH-006.yaml` — `system.services` (+6).
- `tests/test_schema.py` (+74), `tests/test_integration.py` (+53).
- `docs/architecture.md` — topology paragraph.
- Prior commits `324ac3b`, `3af7af1` unchanged; see §2 and `git log --oneline`.

## 4. Current Architecture / State

- **Execution model**: fully in-process. `ExperimentRunner.run_async` → per seed: fresh `Clock`, `MetricsCollector`, `ResiliencePolicy`, N `DependencyService`s (one per graph node, per-target injectors), one shared `ResilientClient`, `SystemUnderTest`, `WorkloadGenerator`. SUT fans out sequentially in `call_order`; first exception wins (maps to 503/504/429/5xx in `sut.handle`). No HTTP in hot path.
- **Determinism**: per-request RNG = `generator_for(seed, request_id, service_salt)`; service index 0 keeps salt `FAULT_RNG_SALT` so legacy runs reproduce exactly. Timing metrics remain wall-clock/statistical only — do NOT assert exact cross-run record counts (a determinism test asserting equal `record_count` across runs was written and removed this session for that reason).
- **Metrics flow**: unchanged; `downstream` rows carry the serving service in `dependency`. `failure_amplification = downstream_rows / request_rows` now counts fan-out calls (can exceed N per request under retries).
- **Known approximation**: one shared policy (single circuit breaker / concurrency limiter / timeout) across all services. Per-service policies are a future extension.
- **Config**: `pyproject.toml` — ruff selects `E,F,I,N,UP,B,SIM,C4,ASYNC`, ignores `E501,B008,SIM108,C901,UP042,N818`; mypy `strict=true`, `python_version="3.12"`; pytest `asyncio_mode=auto`. Python 3.13.14, package installed editable with `[dev,parquet]`.

## 5. Decisions Made

- All prior decisions (§5 of previous handoff) still hold: in-process execution, `str, Enum`, `CallFailure` name, `Rng` protocol, timeout-vs-`DeadlineExceeded` contract, `recovery_time=inf`, mypy target 3.12.
- **Sequential fan-out with short-circuit** (not parallel): models a dependency chain, keeps amplification accounting and the single-`downstream`-callable SUT interface unchanged.
- **Shared policy across services** for this subphase; per-service policy maps left for later (would change `PolicySpec` shape).
- **Strict target validation only in graph mode**: preserves backward compatibility of all existing YAMLs (their arbitrary targets collapse onto `payment_service` as before).
- **`call_order()` on `SystemSpec`**: pure, testable, reused by runner.
- **Additive artifact change only** (`topology` key in `experiment.json`); `reproduce` unaffected (it re-parses `configuration.yaml`, which already round-trips `services` via `dump_yaml`/`load_yaml`).

## 6. Requirements and Constraints

- Preserve: warmup exclusion from ALL metric kinds; per-request seeded determinism (service-0 salt unchanged); `max_attempts` = total attempts semantics; amplification definition; strict mypy + ruff + format clean (`make check`); no `python -m` invocation of `resiliencelab.cli.app` (use installed `resiliencelab` script or `python -m resiliencelab`).
- Do not add code comments unless asked (project convention); type hints + clear naming instead.
- Do not claim Docker verification — Docker is not installed here.
- Benchmark YAMLs follow spec-style convention; `dump_yaml` emits spec-style (round-trips `services`).
- Do not assert wall-clock-derived quantities (request counts, throughput) for exact cross-run equality in tests.

## 7. Testing and Verification

- `python -m pytest` → **67 passed** (was 59; +6 schema, +2 integration).
- `ruff check`, `ruff format --check` (2 files auto-reformatted after edit), `mypy resiliencelab` (strict, 51 files) → all clean.
- CLI E2E (actually executed): `validate` RL-BENCH-006; `run` 1 rep (availability 0.2732, amplification 0.55); `report` shows `services:` topology block.
- Not verified: Docker build/run, Kubernetes apply, PostgreSQL/Redis integration (compose services provisioned but unused — registry is in-memory), `make reproduce-paper` full regeneration, per-service policies, parallel fan-out.
- No known failing tests.

## 8. Known Issues / Risks

- **Shared policy across services**: a breaker opened by one dependency sheds load for all; acceptable for cascade experiments, wrong for isolation studies. Next step if needed: `policy` per service (schema + runner + client wiring).
- **Sequential fan-out only**: no parallel scatter-gather; `depends_on` currently affects order only, not conditional invocation (short-circuit already gives de-facto conditional behavior).
- **Recovery detector needs post-failure observation**: unchanged from before.
- **`bootstrap_ci` default 4000 resamples** can be slow on large record sets; fine at current scale.
- **`record()` uses `threading.Lock`**; safe today (single event loop).
- Debug artifacts in `%TEMP%\opencode` (`bench006/`, etc.) are scratch, not part of the repo.

## 9. Unfinished Work

Remaining larger-vision phases: observability plane (logs/traces), dashboard UI (only API+CLI exist), auth/quotas/isolation, worker scaling (Redis/RQ or Celery), per-service policies, parallel fan-out, adaptive policies (EWMA/AIMD → bandits/RL), full research campaign with figures, `make reproduce-paper` wiring. Extension points: `ResiliencePolicy` (mechanisms), `FaultSpec`/`DependencyService` (faults), `WorkloadGenerator` (arrivals), `analysis/` (metrics), `experiments/factorial.py` (factors), `SystemSpec.services` (topology shapes).

## 10. Next Subphase

Suggested next step (pick one; do not start unprompted broad rewrites):

**Option B — Dashboard** (carried over): minimal read-only web UI (experiment list, run status, comparison table, timeline chart) served alongside the API; reuse `/metrics`, `/timeline`, `/report` endpoints. Verify with TestClient + one live-boot check.

**Option C — Per-service policies**: allow `policy` overrides per service in the graph (e.g. breaker only on payment). Touches `PolicySpec` shape + runner client wiring; design first, keep legacy default.

Before implementing either: run `make check`, read `experiments/runner.py`, `services/sut.py`, `core/schema.py`, and the relevant benchmark YAML. Expected outcome: working feature + tests + docs paragraph, all gates still green.

## 11. Critical Context

- The three runtime bugs that shaped the architecture: (1) nested `httpx.ASGITransport` deadlocks → no HTTP in experiment path; (2) synchronous no-fault call chains starve the event-loop timer → `await asyncio.sleep(0)` in `workloads/generator.py:client_loop`, do not remove; (3) warmup wrote downstream but not request rows → collector `recording` gate in `metrics/collector.py`, do not bypass.
- starlette ≥0.52 `TestClient` never runs `asyncio.create_task` fire-and-forget jobs → API `/run` uses `BackgroundTasks`; `Runtime.submit` is the production path.
- Never name scratch files after stdlib modules (`inspect.py` shadowing incident).
- PowerShell here-strings + `Select-Object` truncate/wrap long lines in tool output; verify suspicious output against the actual file before "fixing".
- Duration-based workloads are wall-clock: never assert exact cross-run equality of counts/timings in tests; assert on seeded RNG behavior or single-run invariants instead.
- Git identity used: `ResilienceLab <resiliencelab@example.com>`; repo has no remote. Topology work is **uncommitted** — commit it (or verify first) before further changes.

## 12. Agent Instructions

- Repository state: topology changes uncommitted (8 files). Start with `git status --short`, `git diff --stat`, then `make check` (or `ruff check` + `mypy` + `pytest -q`).
- Commit the topology work first if the gates are green, then implement exactly one of §10 Option B/C (or an explicitly assigned task), with tests and docs, ending green and committed.
- Do not rewrite the in-process execution model, the exception taxonomy, the timeout contract, the metrics-gating, or the sequential fan-out without understanding §5 and §11.
- Preserve: `Record` alias usage, `Rng` protocol threading, dual YAML conventions, `max_attempts` = total attempts, amplification definition, `recovery_time=inf` semantics, service-0 salt = `FAULT_RNG_SALT`.
