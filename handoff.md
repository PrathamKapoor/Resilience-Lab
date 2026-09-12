# Project Handoff — ResilienceLab

## 1. Current Phase

- **Phase**: Greenfield build (Phase 1 of the larger ResilienceLab vision: experimental core → resilience engine → fault lab → topology → observability → statistics → product → reproducibility → adaptive → deployment → research campaign).
- **Subphase just completed**: Core platform build + hardening. Implemented the experiment platform end-to-end (schema, resilience engine, fault injection, in-process FastAPI SUT/dependency, workload generator, metrics, analysis, runner, artifacts, CLI, REST API, benchmark suite), then hardened it (bug fixes, strict typing, full lint/format/typecheck, deployment configs, docs, paper skeleton).
- **Overall objective**: A reproducible fault-injection and resilience-benchmarking platform for distributed services, suitable for deployment, hackathon demo, and a research paper.
- **Status**: Subphase **complete**. Working tree clean, 2 commits, all quality gates green (59 tests, ruff, ruff format, mypy strict).

## 2. Work Completed

### Core platform (commit `324ac3b`)
- **Resilience engine** (`resiliencelab/resilience/`): retry with status/exception classification and budgets (`retry.py`), fixed/linear/exponential backoff (`backoff.py`), full/equal/range jitter over an `Rng` protocol (`jitter.py`), circuit breaker with closed/open/half-open states, rolling windows, probes, transition listeners (`circuit_breaker.py`), concurrency limiter with queueing/rejection (`concurrency.py`), connect/read/total timeouts with deadline propagation (`timeout.py`), and a composite generic `PolicyExecutor` (`policy.py`) that applies concurrency → circuit-breaker → retry/backoff loop with total-deadline enforcement, emitting `attempt`/`retry`/`rejected` events per call.
- **Fault injection** (`resiliencelab/faults/model.py`): 13 `FailureKind`s, 6 `TemporalMode`s (constant/random/burst/periodic/step/ramp), 4 latency distributions; stateless time-based `FaultInjector.evaluate(now, rng)`.
- **Experiment schema** (`resiliencelab/core/`): Pydantic `ExperimentSpec` with human-friendly `Duration` strings (`100ms`, `5s`), schema→runtime builders, deterministic seeding (`generator`/`generator_for`/`spawn`).
- **Services** (`resiliencelab/services/`): FastAPI `DependencyService` (faults via `invoke()` plus HTTP routes for deployment) and `SystemUnderTest` (direct `handle()` for experiments plus `/order` route); transport-agnostic `ResilientClient` wrapping `PolicyExecutor` with metrics taps.
- **Workload/metrics/analysis**: closed/open/ramp `WorkloadGenerator`; thread-safe `MetricsCollector` with a recording gate; transforms (percentiles, throughput, amplification), per-bucket `timeline.py`, bootstrap CIs/effect sizes (`statistics.py`), comparison, recovery detection, resilience scoring, 2×2 interactions.
- **Runner/artifacts/reports**: `ExperimentRunner` (repetition loop, per-run fresh policy/services, recovery + timeline per run), SHA256-hashed artifact bundles (`artifacts.py`), registry, factorial `generate_matrix`, markdown reports + automatic analysis, 8 benchmark YAMLs (`benchmarks/RL-BENCH-001..008.yaml`), Typer CLI, FastAPI REST API.

### Hardening (commit `3af7af1` plus pre-commit fixes)
- **Warmup-gated metrics**: warmup requests previously wrote downstream/event records but no request records, inflating amplification (observed 6.79 instead of ~3.0). `MetricsCollector` gained a `recording` flag toggled by `WorkloadGenerator.run()` around warmup.
- **Event-loop starvation**: closed-loop tasks spun on fully-synchronous call chains in the no-fault path, starving the duration timer (hang). Added `await asyncio.sleep(0)` per client-loop iteration.
- **Nested ASGI deadlock**: SUT→dependency over `httpx.ASGITransport` hung; replaced with direct in-process `invoke()`/`handle()` calls (single ASGI layer removed entirely).
- **API background tasks**: `asyncio.create_task` fire-and-forget never runs under starlette ≥0.52 httpx-based `TestClient`; run endpoint now uses starlette `BackgroundTasks` (`Runtime.execute_and_store`). `Runtime.submit` (create_task path) retained for real-server use and covered by a dedicated async test.
- **Non-finite statistics**: `summarize`/`mean_ci` wrapped in `np.errstate(invalid="ignore")`; `cohens_d`/`welch_ttest` return NaN for non-finite inputs instead of emitting scipy `RuntimeWarning`s.
- **Timeout semantics**: read/total timeouts surface as retryable `CallFailure(cause=TimeoutError)`; `DeadlineExceeded` is raised only on deadline expiry between attempts. Test asserts this contract.
- **Typing/lint**: mypy `strict=true` clean (51 files), `ruff check` + `ruff format` clean.

## 3. Files Changed

All work is in two commits (`324ac3b`, `3af7af1`); tree is clean. Key files:

- `resiliencelab/resilience/{policy,retry,circuit_breaker,concurrency,backoff,jitter,timeout,errors}.py` — mechanism primitives + composite executor.
- `resiliencelab/faults/model.py`, `resiliencelab/faults/__init__.py` — fault taxonomy + injector.
- `resiliencelab/core/{schema,config,builders,seeds,clock,types,distributions}.py` — schema, dual-convention YAML parsing, builders, RNG.
- `resiliencelab/services/{sut,dependency,client}.py` — SUT, dependency, resilient caller.
- `resiliencelab/workloads/generator.py` — workload driving + warmup gating + starvation yield.
- `resiliencelab/metrics/{collector,transforms,timeline}.py` — `Record = dict[str, Any]` alias lives in `collector.py`; use it for new record-typed code.
- `resiliencelab/analysis/{statistics,comparison,recovery,scoring,interactions}.py`.
- `resiliencelab/experiments/{runner,result,artifacts,registry,factorial,benchmarks,report,provenance}.py`.
- `resiliencelab/cli/app.py` (`init/validate/run/report/compare/reproduce/benchmark/matrix`), `resiliencelab/api/app.py` (all `/api/v1/*` routes; module-level `app = create_app()` is the uvicorn target).
- `benchmarks/RL-BENCH-00{1..8}.yaml`, `configs/example.yaml`.
- `tests/`: `test_resilience.py` (28), `test_faults.py` (8), `test_schema.py` (6), `test_analysis.py` (6), `test_determinism.py` (4), `test_api.py` (4), `test_integration.py` (3).
- `deployment/docker/Dockerfile`, `deployment/docker-compose.yml` (api/postgres/redis), `deployment/kubernetes/{deployment,service,configmap}.yaml`, `.env.example`.
- `docs/{quickstart,architecture,benchmarks,api,reproducibility}.md`, `paper/{outline,reproduce}.md`, `README.md`, `Makefile`, `pyproject.toml` (ruff/mypy/pytest config; `types-PyYAML` + `scipy-stubs` in dev extras).

## 4. Current Architecture / State

- **Execution model**: fully in-process by default. `ExperimentRunner.run_async` → per seed: fresh `Clock`, `MetricsCollector`, `ResiliencePolicy`, `DependencyService`, `ResilientClient`, `SystemUnderTest`, `WorkloadGenerator`. Workload `send` calls `sut.handle()` directly; SUT calls `dependency.invoke()` via `ResilientClient.execute()` under the policy. No HTTP/transport in the hot path. FastAPI routes exist only for real deployments.
- **Determinism**: per-request RNG = `generator_for(seed, request_id)`; dependency faults use a separate salted stream (`FAULT_RNG_SALT`). Same seed ⇒ identical fault decisions/jitter. Timing metrics are wall-clock and only statistically reproducible.
- **Metrics flow**: `PolicyExecutor` `on_event` → `ResilientClient` records `downstream` (per attempt) and `event` rows; workload records `request` rows; circuit-breaker transitions recorded via listener. Warmup excluded via collector gate. `failure_amplification = downstream_rows / request_rows` (can be < 1 when the breaker sheds load — correct per definition).
- **API runtime**: `Runtime` holds `ExperimentRegistry` + `ExperimentRunner` + `jobs` dict. `/run` uses `BackgroundTasks` → `execute_and_store`; `/status` reads `jobs`.
- **Config**: `pyproject.toml` — ruff selects `E,F,I,N,UP,B,SIM,C4,ASYNC`, ignores `E501,B008,SIM108,C901,UP042,N818`; mypy `strict=true`, `python_version="3.12"`; pytest `asyncio_mode=auto`. Installed env: Python 3.13.14, package installed editable with `[dev,parquet]`.

## 5. Decisions Made

- **In-process over HTTP for experiments** (after nested-ASGI deadlock): determinism, speed (~6k rps), no flaky transport. Real HTTP reserved for deployment. Do not reintroduce httpx between SUT and dependency without addressing the deadlock/starvation findings.
- **`str, Enum` kept for all enums** (UP042 ignored): explicit pydantic-compatible pattern; `StrEnum` would change `f"{member}"` formatting.
- **`CallFailure` not renamed** (N818 ignored): domain term for the shared exception taxonomy alongside `*Error` subclasses.
- **`Rng` Protocol** (`jitter.py`) threaded through `PolicyExecutor`/`ResilientClient`/`DownstreamCallable`/runner instead of `object`: satisfies strict mypy while numpy generators satisfy it structurally at runtime.
- **Timeout contract**: timeouts are retryable `CallFailure`s, not `DeadlineExceeded` (see §2). Preserve; tests pin it.
- **`recovery_time = inf`** when no sustained post-failure recovery is observed; statistics propagate NaN/inf with exposed NaN effect sizes. Honest, not a bug.
- **mypy target 3.12** while `requires-python >=3.11`: installed numpy stubs use 3.12-only syntax; code itself stays 3.11-compatible.

## 6. Requirements and Constraints

- Preserve: warmup exclusion from ALL metric kinds; per-request seeded determinism; `max_attempts` = total attempts semantics; amplification definition; strict mypy + ruff + format clean (`make check`); no `python -m` invocation of `resiliencelab.cli.app` (use installed `resiliencelab` script or `python -m resiliencelab`).
- Do not add code comments unless asked (project convention); type hints + clear naming instead.
- Do not claim Docker verification — Docker is not installed here; Dockerfile/compose/k8s manifests are authored but only the uvicorn boot was live-tested.
- Benchmark YAMLs follow the spec-style convention (identity under `experiment:`, rest top-level); `parse_experiment` also accepts fully-nested form. `dump_yaml` emits spec-style.

## 7. Testing and Verification

- `python -m pytest -q` → **59 passed** (28 resilience incl. hypothesis property tests, 8 faults, 6 schema, 6 analysis, 4 determinism/factorial, 4 API, 3 integration).
- `ruff check`, `ruff format --check`, `mypy resiliencelab` (strict, 51 files) → all clean.
- CLI E2E (all actually executed): `validate` on all 8 benchmarks; `run` ×2 policies → `compare` (effect sizes) → `report` → `reproduce` (0.3794 vs 0.3763 availability, consistent) → `matrix` (4 variants + `matrix_comparison.json`).
- API: TestClient suite green; live `uvicorn resiliencelab.api.app:app` boot verified serving `/api/v1/workloads`.
- Not verified: Docker build/run, Kubernetes apply, PostgreSQL/Redis integration (compose services are provisioned but unused by code — registry is in-memory), `make reproduce-paper` full-paper regeneration, multi-service/cascading topology (RL-BENCH-006 runs staged faults against the single dependency).
- No known failing tests. Warnings eliminated (non-finite stats guards).

## 8. Known Issues / Risks

- **Single-dependency topology**: runner wires one `payment_service`; `FailureSpec.target` values other than that are accepted but all injectors attach to the same dependency. Multi-service graphs are the biggest architectural gap (spec Phase 4).
- **`ExperimentRunner()` is single-node in-process**: no worker queue, quotas, auth, or isolation (spec Phases 9–10). `matrix` runs variants sequentially.
- **Recovery detector needs post-failure observation**: short runs after a burst yield `inf` recovery (correct but uninformative); benchmark durations account for this, tiny demo configs may not.
- **`bootstrap_ci` default 4000 resamples** can be slow on large record sets; fine at current scale.
- **`record()` uses `threading.Lock`**; safe today (single event loop) but revisit if a threaded server mode is added.
- Debug scripts in `%TEMP%\opencode` (`dbg*.py`, `e2e_*`, `results*`) are scratch, not part of the repo.

## 9. Unfinished Work

Per the larger vision, remaining phases: distributed multi-service topology + cascading, observability plane (logs/traces beyond metrics), dashboard UI (only API+CLI exist), auth/quotas/isolation, worker scaling (Redis/RQ or Celery), adaptive policies (threshold/EWMA/AIMD → bandits/RL), full research campaign with figures, `make reproduce-paper` wiring. None of this was in scope for the completed subphase; the extension points are `ResiliencePolicy` (new mechanisms), `FaultSpec`/`DependencyService` (new faults), `WorkloadGenerator` (new arrivals), `analysis/` (new metrics), `experiments/factorial.py` (new factors).

## 10. Next Subphase

Suggested next step (pick one; do not start unprompted broad rewrites):

**Option A — Multi-service topology** (highest research value): extend `ExperimentSpec.system` with a service graph, instantiate N `DependencyService`s with per-target injector routing in `runner._injectors`/`_run_once` (route by `FailureSpec.target` instead of the hardcoded `payment_service`), add topology to artifacts + report, add integration test with two dependencies and a cascading scenario.

**Option B — Dashboard**: minimal read-only web UI (experiment list, run status, comparison table, timeline chart) served alongside the API; reuse `/metrics`, `/timeline`, `/report` endpoints. Verify with TestClient + one live-boot check.

Before implementing either: run `make check`, read `experiments/runner.py`, `services/sut.py`, `core/schema.py`, and the relevant benchmark YAML. Expected outcome: working feature + tests + docs paragraph, all gates still green.

## 11. Critical Context

- The three runtime bugs that shaped the architecture: (1) nested `httpx.ASGITransport` deadlocks → no HTTP in experiment path; (2) synchronous no-fault call chains starve the event-loop timer → `await asyncio.sleep(0)` in `workloads/generator.py:client_loop`, do not remove; (3) warmup wrote downstream but not request rows → collector `recording` gate in `metrics/collector.py`, do not bypass.
- starlette ≥0.52 `TestClient` never runs `asyncio.create_task` fire-and-forget jobs → API `/run` uses `BackgroundTasks`; `Runtime.submit` is the production path.
- `C:\Users\LENOVO\AppData\Local\Temp\opencode\inspect.py` once shadowed stdlib `inspect` and broke a debug session; never name scratch files after stdlib modules.
- PowerShell here-strings + `Select-Object` truncate/wrap long lines in tool output; verify suspicious output (e.g. empty CIs) against the actual file before "fixing".
- Git identity used: `ResilienceLab <resiliencelab@example.com>`; repo has no remote.

## 12. Agent Instructions

- Repository state: clean tree at `3af7af1`, all gates green. Start with `git log --oneline`, `README.md`, `docs/architecture.md`, then the module you need to touch.
- Run `make check` (or `ruff check` + `mypy` + `pytest -q`) before and after any change; keep all three green.
- Do not rewrite the in-process execution model, the exception taxonomy, the timeout contract, or the metrics-gating without understanding §5 and §11.
- Preserve: `Record` alias usage, `Rng` protocol threading, dual YAML conventions, `max_attempts` = total attempts, amplification definition, `recovery_time=inf` semantics.
- Next objective: implement exactly one of §10 Option A/B (or an explicitly assigned task), with tests and docs, ending green and committed.
