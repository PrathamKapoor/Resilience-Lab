# Simulation model

> **ResilienceLab uses controlled in-process simulation.** Service processing
> time, network delay, network jitter, queueing, and service capacity are
> *simulated* phenomena. They are not measurements of any actual network or
> production infrastructure, and a configured 50 ms delay does not guarantee a
> real host would observe 50 ms.

## Why simulation?

The simulator is a methodological choice, not a placeholder. It provides
controlled execution, cheap large-scale experimentation, deterministic fault
injection, reproducible seeds, and reduced infrastructure noise. Deployment
(see `deployment/`) targets the ResilienceLab *control plane*, not the
simulated services.

## Simulated vs wall-clock time

Every experiment runs against the wall clock: workloads last real seconds,
metrics carry real timestamps, and recovery is detected over real time.

The *delays* contributed by the simulation (processing, network, and queue
waiting) are explicit, seeded quantities; the *measurement* of how long a
request took is wall-clock. Simulated delays are applied with `asyncio.sleep`
because the whole experiment pipeline is wall-clock driven; this is efficient
in-process and keeps the deterministic seeded *decisions* separate from
wall-clock *measurement*.

## Components of a dependency call

```text
caller
   │
   ▼ network latency (+jitter)      — simulated, seeded
   ▼ service queue wait             — wall-clock (a slot may genuinely be occupied)
   ▼ service processing latency     — simulated, seeded
   ▼ fault injection                — existing fault model
   ▼ response
```

## Configuration

### Service processing (`system.services[].processing`)

Simulated per-request processing latency. `None` means zero (instantaneous).

| Field | Meaning | Default |
|---|---|---|
| `distribution` | `constant` / `uniform` / `normal` / `lognormal` / `pareto` | `constant` |
| `mean` | base/mean delay (constant value when `constant`) | `0` |
| `std` | standard deviation (`normal`, `lognormal`, fallback uniform) | `0` |
| `min` / `max` | bounds (`uniform`, `pareto` offset) | `0` |

### Service capacity (`system.services[].capacity`)

Service-side concurrent processing slots — a different experimental variable
from the client-side concurrency limit in the resilience policy.

| Field | Meaning | Default |
|---|---|---|
| `max_concurrency` | number of simultaneous processing slots | `50` |
| `queue_limit` | `None` (unbounded queue), `0` (reject when saturated), `N` (bounded) | `None` |

A service-side rejection surfaces as a retryable `503` (`ServiceSaturated`),
so it interacts with retries exactly like a transient dependency error.

### Network (`system.network`)

Simulated per-call network latency applied on the caller→dependency edge.

```yaml
network:
  default:
    latency: 20ms
    jitter: 5ms
  edges:
    - source: order_api
      target: payment
      latency: 40ms
      jitter: 10ms
```

`default` applies to every edge; a matching `edges` entry overrides it (matched
by `target`, with `source` used as a tie-breaker). A missing `network` block
means zero network delay.

## Determinism

Processing latency, network latency, and network jitter sample from the same
seed architecture as faults:

- processing: `generator_for(seed, request_id, service_salt, PROCESSING_RNG_SALT)`
- network:    `generator_for(seed, request_id, NETWORK_RNG_SALT, service_index)`

The same experiment configuration + seed yields the same simulated stochastic
decisions (Layer A in `docs/reproducibility.md`). Queue/reject outcomes are
deterministic given arrival order, but arrival order, request counts,
throughput, queue waits, and wall-clock completion times vary by host and
scheduling (Layer B). Do not claim same-seed identical metrics.

## Metrics

`latency_components` reports the mean simulated `network`, `processing`, and
wall-clock `queue` wait, alongside `total`/`service`/`retry`/`other`. Each
`downstream` record carries `network_latency`, `processing_latency`,
`queue_wait`, and `service_rejected`. Queue/reject events are emitted as
`service_queued` / `service_rejected`, and each run records a per-service
capacity snapshot (`capacity`, `in_flight`, `queue_depth`, `peak_queue_depth`,
`utilization`, `rejected_count`).