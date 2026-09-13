# Workload model

A workload specifies the traffic that drives the system under test. ResilienceLab
distinguishes **closed-loop** (client-driven) traffic from **arrival processes**
(every other mode), which emit requests according to an inter-arrival rule.

All arrival processes are pure, seeded functions of `(elapsed time, rng)`: the
inter-arrival gap they return is deterministic for a given seed and elapsed time.
Only the wall-clock *scheduling* of those gaps (via `asyncio.sleep`) is
non-reproducible. This keeps stochastic decisions reproducible while explicitly
allowing measured completion times to vary.

## Modes

| `type` | Behavior |
|---|---|
| `closed_loop` | `clients` concurrent loops each issue a request, await the response, then immediately issue another. Traffic is response-limited (saturates against service latency). `arrival_rate` and `distribution` are not used. |
| `open_loop` | Arrivals independent of completions. Inter-arrival gap drawn from `distribution`: `poisson`/`exponential` → `Exponential(1/rate)`, `constant` → fixed `1/rate`. |
| `constant_rate` | Deterministic fixed inter-arrival gap `1 / arrival_rate`. |
| `random` | Inter-arrival gap ~ `Uniform(0, 2 / arrival_rate)` (renewal process with mean `1/rate`). |
| `burst` | Alternates: `burst_size` arrivals at gap `1/arrival_rate`, then an idle `burst_interval`, repeating. |
| `periodic` | Arrival rate oscillates sinusoidally with `period` and amplitude `burstiness`: `rate(t) = arrival_rate · (1 + burstiness · sin(2πt / period))`, floored near zero. |
| `ramp` | Rate ramps linearly from `10%` of `arrival_rate` to full rate over `duration`. |

## Relevant fields

| Field | Meaning | Default |
|---|---|---|
| `arrival_rate` | Target arrivals per second (requests/s). | `100` |
| `clients` | Concurrent clients (closed-loop only). | `10` |
| `duration` / `warmup` / `cooldown` | Run length; warmup traffic is never recorded. | `60s` / `0` / `0` |
| `distribution` | Inter-arrival distribution for `open_loop`. | `poisson` |
| `burst_size` | Requests per active window (`burst`). | `10` |
| `burst_interval` | Idle gap between bursts (`burst`). | `1s` |
| `period` | Oscillation period (`periodic`). | `1s` |
| `burstiness` | Oscillation amplitude (`periodic`). | `1.0` |
| `payload_size` | Accepted, not yet wired into the in-process SUT. | `64` |
| `endpoint_mix` | Accepted, not yet wired (single logical endpoint). | `["/"]` |

## Latency measurement semantics

`request.latency` is the **total wall-clock time** from request issue to response
or exception. It decomposes as:

```text
total = service + backoff + other
```

- **service**: sum over attempts of `downstream.latency` — simulated dependency
  processing (injected fault/saturation delay included).
- **backoff**: sum of scheduled retry backoff sleeps.
- **other**: concurrency queue wait, circuit-open wait, timeout waits, and
  event-loop scheduling — the residual `total − service − backoff`.

This decomposition is reported per experiment under "Measurement semantics".
Within the `service` component, the simulated network and processing latency
and the wall-clock queue wait are further attributed (see `docs/simulation.md`).