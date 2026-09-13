# Architecture

ResilienceLab is a modular experimentation platform. The experiment — not any
single framework — is the central abstraction.

```text
CLI / REST API
      │
ExperimentRunner (experiments/runner.py)
      ├── ExperimentSpec (core/schema.py, validated by Pydantic)
      ├── ResiliencePolicy (resilience/policy.py: retry, backoff, jitter,
      │                     circuit breaker, concurrency, timeout)
      ├── FaultInjector list (faults/model.py)
      ├── Simulated network (services/network.py)
      ├── DependencyService (services/dependency.py): capacity/queue + processing
      ├── SystemUnderTest (services/sut.py)
      ├── WorkloadGenerator (workloads/generator.py)
      └── MetricsCollector (metrics/collector.py)
            │
            ▼
Analysis (analysis/): statistics, comparison, recovery, scoring, interactions
            │
            ▼
Artifacts (experiments/artifacts.py): configuration, raw records, analysis,
timeline, report, manifest with SHA256 hashes
```

## Simulation model

Dependency services are simulated: each call flows through a seeded network
delay, an explicit service-side capacity/queue, a seeded processing delay, and
fault injection. See `docs/simulation.md` for full semantics and the
explicit simulation/wall-clock distinction.

## Policy resolution

Resilience policies are scoped to the destination service. A single global
`policy` plus optional per-service `policies` overrides are resolved by
`core/policies.py` into one independent runtime policy (circuit breaker,
concurrency limiter, retry) per dependency. See `docs/policies.md`.

Key design decisions:

- In-process execution by default. Services are FastAPI apps for real HTTP
  deployments, but experiments invoke them directly in-process for
  determinism and speed. Per-request randomness is derived from
  `(seed, request_id)` via `core/seeds.py`, so fault decisions and jitter are
  reproducible independent of scheduling.
- Transport-agnostic resilience primitives (`resilience/`) with a shared
  exception taxonomy (`CallFailure` and subclasses).
- Warmup traffic is generated but never recorded: the collector is gated so
  warmup cannot inflate amplification or latency statistics.
- Workloads are either client-driven (`closed_loop`) or arrival processes whose
  inter-arrival gaps are pure, seeded functions of elapsed time (`workloads/arrivals.py`);
  see `docs/workloads.md` for the mode semantics and latency-attribution model.
- Controlled simulation: network latency/jitter, service processing time, and
  service capacity/queueing are simulated, seeded phenomena (`services/network.py`,
  `services/processing.py`, `services/capacity.py`) — distinct from the
  client-side concurrency limit. See `docs/simulation.md`.
- Multi-service topology: `system.services` declares a dependency graph
  (`name` plus `depends_on`). The runner instantiates one
  `DependencyService` per entry, routes each `failure` entry's injectors to
  the service named by its `target` (validated against the graph), and the
  SUT fans out sequentially in topological (`call_order`) order,
  short-circuiting on the first failure — so an upstream outage cascades by
  sparing downstream services the call. Each service draws faults from an
  independent per-service salted RNG stream, keeping same-seed runs
  reproducible. Omitting `services` preserves the legacy single
  `payment_service` behavior. RL-BENCH-006 exercises this with a staged
  payment/inventory cascade.
- Every result carries provenance: configuration hash, environment capture,
  seeds, and hashed raw records.
