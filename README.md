# ResilienceLab

A reproducible fault-injection, resilience benchmarking, and policy evaluation
platform for distributed services.

ResilienceLab does not merely demonstrate that resilience mechanisms exist. It
experimentally determines **when, why, and at what cost** different resilience
mechanisms work — with controlled failures, reproducible workloads, repeated
trials, uncertainty reporting, and manifest-hashed artifacts.

The services are **controlled in-process simulations** (processing time,
network delay, queueing, and capacity), not a production infrastructure. See
`docs/simulation.md` for the full and honest model.

## Capabilities

- Resilience mechanisms: retries, fixed/linear/exponential backoff, full/equal/range jitter, circuit breaker (closed/open/half-open), concurrency limiting with queueing/rejection, read/total timeouts (`connect` is schema-only, no runtime effect) — with optional per-service policy overrides (isolated breaker/concurrency/retry state per dependency).
- Fault injection: HTTP 500/502/503/429, connection reset/refusal, timeouts, latency injection and spikes, saturation; constant/random/burst/periodic/step/ramp temporal modes.
- Controlled simulation: per-service processing latency (constant/uniform/normal/lognormal/Pareto), inter-service network latency and jitter, service-side capacity with bounded/unbounded queues and rejection.
- Standardized benchmark suite RL-BENCH-001..018 (see `docs/benchmarks.md`).
- Reproducible workloads (open/closed loop, constant-rate, ramp) with warmup excluded from measurement. Seeded decisions are deterministic; wall-clock execution (counts, throughput, queueing, recovery) may vary — see `docs/reproducibility.md` layers A/B/C.
- Metrics: availability, throughput, p50/p90/p95/p99/p99.9, error/timeout rates, recovery phases, retry depth, circuit transitions, and failure amplification (downstream calls per upstream request).
- Analysis: t-based confidence intervals by default (bootstrap available opt-in, not the default for artifacts/compare/matrix unless explicitly configured), effect sizes, cross-policy comparison, interaction effects, composite scoring with exposed weights.
- Observability: a canonical, ordered, correlated event stream (requests, dependencies, retries, timeouts, breaker transitions, queue/capacity, network, faults) persisted as hashed artifacts with causal traces and filtering (see `docs/events.md`).
- Interfaces: Typer CLI, versioned REST API with OpenAPI docs.
- Reproducibility: every run stores configuration, environment, raw records, analysis, timeline, report, and a SHA256 manifest (integrity, not correctness); `reproduce` reruns from the stored configuration (`--all` for paper benchmarks, with a machine-readable manifest).

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

### Dashboard

The React dashboard is served by FastAPI at [`/dashboard`](/dashboard) after a
production build. It presents one selected experiment's recorded metrics,
timeline markers, events, analysis, and report; it does not add a dashboard
database or change experiment execution.

For local development, use two terminals from the repository root:

```bash
# terminal 1: local FastAPI mode has anonymous access and in-memory experiments
uvicorn resiliencelab.api.app:app --host 127.0.0.1 --port 8000

# terminal 2: Vite proxies /api to terminal 1
npm --prefix dashboard ci
npm --prefix dashboard run dev
```

Open `http://127.0.0.1:5173/dashboard/`. To add and run the existing example
through the same API the dashboard reads, use a third terminal:

```bash
resiliencelab server submit configs/example.yaml
resiliencelab server run exp_demo
resiliencelab server status exp_demo
```

`configs/example.yaml` has five sequential 60-second repetitions, so stage a
completed run before a short demonstration. In local mode the FastAPI process
holds the result only in memory, and `resiliencelab server status exp_demo` is
the source of the completed state. The dashboard loads evidence after that
state, but its local experiment-detail header can still show `created` and no
config hash; use the full report's recorded `Config SHA256` instead.

To exercise FastAPI's production static serving locally, build the frontend
first, then open `http://127.0.0.1:8000/dashboard`:

```bash
npm --prefix dashboard ci
npm --prefix dashboard run build
uvicorn resiliencelab.api.app:app --host 127.0.0.1 --port 8000
```

The production image builds the frontend in the pinned
`node:22.14.0-bookworm-slim` stage with `npm ci` and `npm run build`. Only
`dashboard/dist` is copied into the non-root Python runtime image. Build it
with `docker compose -f deployment/docker-compose.yml build`.

Docker Compose enables server mode, API-key authentication, PostgreSQL, Redis,
and the worker. Set its required values in an untracked `.env`, start its data
services, migrate, then start the application services. Copy `.env.example`;
its database URL explicitly selects the installed psycopg3 SQLAlchemy driver
with `postgresql+psycopg://`:

```bash
docker compose -f deployment/docker-compose.yml up -d postgres redis
docker compose -f deployment/docker-compose.yml run --rm --no-deps \
  api alembic upgrade head
docker compose -f deployment/docker-compose.yml up -d api worker
```

The browser bundle deliberately contains no production API key. As a result,
the Compose configuration serves the dashboard assets at `/dashboard`, but it
does **not** provide a browser login or API-key injection mechanism for its
protected `/api/v1` data routes. Put an authenticated same-origin gateway or
session mechanism in front of it before using the server-mode dashboard; do
not place `RESILIENCELAB_API_KEYS` or `VITE_RESILIENCELAB_API_KEY` in a
production bundle. `VITE_RESILIENCELAB_API_KEY` is development-only and may be
used when testing a protected API through Vite. It is compiled into and exposed
to the local browser bundle; Vite's proxy does not keep that header server-side.
Use only a non-production key for this local workflow.

Metric provenance and dashboard data flow are documented in
[`docs/architecture-dashboard.md`](docs/architecture-dashboard.md). The
repeatable 180-second judge flow is in [`docs/demo-script.md`](docs/demo-script.md).

```bash
docker compose -f deployment/docker-compose.yml up
```

Kubernetes manifests and their required external services are documented in
[`deployment/kubernetes/README.md`](deployment/kubernetes/README.md).

## Repository layout

```text
resiliencelab/   core, resilience, faults, workloads, services,
                 metrics, analysis, experiments, api, cli
benchmarks/      RL-BENCH-001..018
configs/         example experiment configuration
docs/            quickstart, architecture, benchmarks, api, reproducibility,
                 workloads, simulation, policies, events
paper/           research outline and reproduction notes
deployment/      Dockerfile, compose, kubernetes manifests
tests/           unit, property-based, integration, API tests
```

## Research

See `paper/outline.md` for research questions, method, and threats to validity.
