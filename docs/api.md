# API reference

Base path: `/api/v1`. Interactive docs at `/docs` when serving with uvicorn.

| Method | Path | Description |
|--------|------|-------------|
| POST | /experiments | Register an experiment configuration (`{"config": {...}}`) |
| GET | /experiments | List registered experiment IDs |
| GET | /experiments/{id} | Fetch the experiment configuration |
| POST | /experiments/{id}/run | Execute the experiment as a background task |
| GET | /experiments/{id}/status | `running`, `completed`, or `failed` |
| GET | /experiments/{id}/metrics | Per-run primary metrics |
| GET | /experiments/{id}/timeline | Per-bucket correlated timeline per run |
| GET | /experiments/{id}/report | Human-readable markdown report |
| GET | /experiments/{id}/analysis | Automatic analysis summary |
| GET | /benchmarks | Standard benchmark names |
| GET | /policies | Supported resilience mechanisms |
| GET | /fault-models | Failure types and temporal modes |
| GET | /workloads | Supported workload types |

Example:

```bash
curl -X POST localhost:8000/api/v1/experiments \
  -H 'Content-Type: application/json' \
  -d '{"config": {"experiment": {"id": "exp_api", "name": "api smoke"}}}'
curl -X POST localhost:8000/api/v1/experiments/exp_api/run
curl localhost:8000/api/v1/experiments/exp_api/status
```
