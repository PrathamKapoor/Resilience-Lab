# ResilienceLab

A reproducible fault-injection, resilience benchmarking, and policy evaluation
platform for distributed services.

ResilienceLab does not merely demonstrate that resilience mechanisms exist. It
experimentally determines **when, why, and at what cost** different resilience
mechanisms work — with controlled failures, reproducible workloads, repeated
trials, uncertainty reporting, and hashed immutable artifacts.

The services are **controlled in-process simulations** (processing time,
network delay, queueing, and capacity), not a production infrastructure. See
`docs/simulation.md` for the full and honest model.

## Capabilities

- Resilience mechanisms: retries, fixed/linear/exponential backoff, full/equal/range jitter, circuit breaker (closed/open/half-open), concurrency limiting with queueing/rejection, connect/read/total timeouts — with optional per-service policy overrides (isolated breaker/concurrency/retry state per dependency).
- Fault injection: HTTP 500/502/503/429, connection reset/refusal, timeouts, latency injection and spikes, saturation; constant/random/burst/periodic/step/ramp temporal modes.
- Controlled simulation: per-service processing latency (constant/uniform/normal/lognormal/Pareto), inter-service network latency and jitter, service-side capacity with bounded/unbounded queues and rejection.
- Standardized benchmark suite RL-BENCH-001..014 (see `docs/benchmarks.md`).
- Reproducible workloads (open/closed loop, constant-rate, ramp) with warmup excluded from measurement.
- Metrics: availability, throughput, p50/p90/p95/p99/p99.9, error/timeout rates, recovery phases, retry depth, circuit transitions, and failure amplification (downstream calls per upstream request).
- Analysis: bootstrap confidence intervals, effect sizes, cross-policy comparison, interaction effects, composite scoring with exposed weights.
- Interfaces: Typer CLI, versioned REST API with OpenAPI docs.
- Reproducibility: every run stores configuration, environment, raw records, analysis, timeline, report, and a SHA256 manifest; `reproduce` reruns from the manifest.

## Install

```bash
python -m pip install -e ".[dev]"
```

Requires Python 3.11+.

## Quickstart

```bash
resiliencelab validate configs/example.yaml
resiliencelab run configs/example.yaml --store ./results
resiliencelab report exp_demo --store ./results
resiliencelab benchmark RL-BENCH-003 --repetitions 1
resiliencelab matrix configs/example.yaml --store ./results
```

Or start the API:

```bash
uvicorn resiliencelab.api.app:app --host 0.0.0.0 --port 8000
```

More in `docs/quickstart.md`.

## Testing and quality

```bash
make check   # ruff + mypy (strict) + pytest
make test
```

## Deployment

```bash
docker compose -f deployment/docker-compose.yml up
```

Kubernetes manifests live in `deployment/kubernetes/`.

## Repository layout

```text
resiliencelab/   core, resilience, faults, workloads, services,
                 metrics, analysis, experiments, api, cli
benchmarks/      RL-BENCH-001..012
configs/         example experiment configuration
docs/            quickstart, architecture, benchmarks, api, reproducibility,
                 workloads, simulation, policies
paper/           research outline and reproduction notes
deployment/      Dockerfile, compose, kubernetes manifests
tests/           unit, property-based, integration, API tests
```

## Research

See `paper/outline.md` for research questions, method, and threats to validity.
