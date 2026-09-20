# Dashboard architecture and metric provenance

## Scope

The dashboard is a Vite + React application in `dashboard/`, served by the
existing FastAPI application at `/dashboard`. It is a read-only view of a
selected experiment. It does not create a database, change experiment
lifecycle behaviour, or synthesize missing measurements.

In development, Vite serves `http://127.0.0.1:5173/dashboard/` and proxies
`/api` to FastAPI on port 8000. In a production build, Vite emits
`dashboard/dist`; FastAPI serves `/dashboard`, hashed assets under
`/dashboard/assets/`, and nested client routes. The HTML entry point is
`no-cache`; hashed assets are immutable-cacheable. FastAPI registers
`/api/v1` before the dashboard routes, so the SPA cannot shadow the API.

```text
Browser
  |-- development: Vite /dashboard/ --proxies /api--> FastAPI
  `-- production: FastAPI /dashboard/ -------------> FastAPI /api/v1
                                                         |
                                      local runtime or server-mode worker
                                                         |
                                     experiment results and artifacts
```

The Docker build uses a pinned `node:22.14.0-bookworm-slim` builder. It runs
`npm ci` and `npm run build`, then copies only `/dashboard/dist` into the
existing Python image with ownership assigned to the existing non-root
`resiliencelab` user. The Python runtime retains its existing non-root user,
data volume, and API-key server-mode defaults. Both Compose application
services use the same locally tagged image.

## API inputs

For the selected id in the `experiment` URL query parameter, the application
uses these existing authenticated, same-origin endpoints:

| Purpose | Endpoint | Dashboard use |
| --- | --- | --- |
| Selector | `GET /api/v1/experiments` | Lists available experiments. |
| Identity and state | `GET /api/v1/experiments/{id}` | Name, description, status, update time, and config hash. |
| Running state | `GET /api/v1/experiments/{id}/status` | Polls every five seconds until a terminal state, and stops while the tab is hidden. |
| Run measurements | `GET /api/v1/experiments/{id}/metrics` | Supplies `metrics_per_run` for displayed means. |
| Timeline buckets | `GET /api/v1/experiments/{id}/timeline` | Supplies the displayed run/bucket count. |
| Causal events | `GET /api/v1/experiments/{id}/events` | Supplies fault, recovery, circuit, and recent-signal markers. |
| Narrative and analysis | `GET /api/v1/experiments/{id}/analysis`, `/report` | Supplies recorded policy text and a conditional recommendation. |

All browser requests use `credentials: same-origin`. A development-only
`VITE_RESILIENCELAB_API_KEY` can add `X-API-Key` through Vite; production code
does not read or embed it. Server-mode Compose therefore needs a same-origin
authentication gateway or session mechanism before protected dashboard data
can be viewed in a browser. It is intentionally not safe to solve that by
shipping an API key to the client.

## Metric provenance

The current interface shows five observed means across the selected
experiment's `metrics_per_run` response:

| Dashboard label | Source field | Transformation | When unavailable |
| --- | --- | --- | --- |
| Availability | `availability` | Arithmetic mean × 100 | Shown as “Not recorded”. |
| p99 latency | `p99_latency_ms`, else `latency_p99` | Arithmetic mean; `latency_p99` is converted from seconds to milliseconds | Shown as “Not recorded”. |
| Error rate | `error_rate` | Arithmetic mean × 100 | Shown as “Not recorded”. |
| Throughput | `throughput` | Arithmetic mean in requests/second | Shown as “Not recorded”. |
| Recovery time | `recovery_time` | Arithmetic mean in seconds | Shown as “Not recorded”. |

These are simulator experiment metrics, not telemetry from a production
service. Fault and recovery statements come from the canonical event stream
(`FaultInjected`, `FaultRecovered`, `CircuitOpened`, `CircuitHalfOpened`,
`CircuitClosed`, and relevant service recovery events), and the timeline
bucket count comes from the recorded per-run timeline. See
[`events.md`](events.md) for event ordering and
[`reproducibility.md`](reproducibility.md) for determinism and artifact limits.

The design brief mentions a resilience score and error-budget consumption, but
the current endpoints and UI do not expose a defined value for either. They
are not displayed or inferred.

## Policy recommendation boundary

The policy card displays an explicit `analysis.recommendation` string when the
analysis endpoint supplies one, or a concrete `Recommendation:` line from the
recorded report. Placeholder text such as “see comparison analysis” is treated
as insufficient evidence. In that case the UI says so instead of ranking
policies. The dashboard is not an adaptive ranked recommender; a defensible
cross-policy conclusion requires recorded comparison or interaction analysis.

## Reproducibility boundary

The experiment header exposes the API's recorded configuration hash. Server
artifacts retain the configuration, seeds, raw records, timelines, report,
statistics, and SHA256 manifest. A matching manifest establishes recorded-file
integrity, not scientific correctness, and seeded decisions do not make
wall-clock metrics bit-identical. Use `resiliencelab reproduce <id>` against a
CLI-created artifact bundle or the artifact APIs to inspect the retained
evidence; do not treat the dashboard as an artifact verifier.
