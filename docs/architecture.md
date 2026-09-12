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
      ├── SystemUnderTest (services/sut.py) + DependencyService (services/dependency.py)
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
- Every result carries provenance: configuration hash, environment capture,
  seeds, and hashed raw records.
