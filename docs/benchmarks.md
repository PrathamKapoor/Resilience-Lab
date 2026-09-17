# Benchmark suite

| ID | Name | What it measures |
|----|------|------------------|
| RL-BENCH-001 | intermittent-errors | Availability/latency under random 503s |
| RL-BENCH-002 | latency-injection | Tail latency and timeout behavior under degradation |
| RL-BENCH-003 | burst-outage | Degradation, mitigation, and recovery across an outage |
| RL-BENCH-004 | dependency-saturation | Behavior under constrained downstream capacity |
| RL-BENCH-005 | retry-storm | Downstream request amplification from retries |
| RL-BENCH-006 | cascading-failure | Staged multi-target failure propagation |
| RL-BENCH-007 | recovery-dynamics | Time to degradation/stabilization/recovery |
| RL-BENCH-008 | non-stationary-failure | Policy robustness when failure type changes mid-run |
| RL-BENCH-009 | service-processing-latency | Simulated service processing latency vs stable client |
| RL-BENCH-010 | network-latency-and-jitter | Simulated network delay and jitter under timeouts |
| RL-BENCH-011 | capacity-saturation | Fixed service capacity saturated by arrival load |
| RL-BENCH-012 | retry-amplification-under-saturation | Retry pressure against a saturated dependency |
| RL-BENCH-013 | per-service-retry-isolation | Independent retry policies per service under comparable failures |
| RL-BENCH-014 | per-service-breaker-isolation | Independent circuit breaker and retry state per dependency |
| RL-BENCH-015 | retry-causal-trace | Failure → retry → outcome reconstructable from events |
| RL-BENCH-016 | saturation-recovery-trace | Queueing/saturation/rejection/recovery observable as events |
| RL-BENCH-017 | timeout-cascade | Timeout propagation through a dependency chain |
| RL-BENCH-018 | retry-by-capacity-factorial | Full-factorial design quantifying when retries improve availability |

Run one with:

```bash
resiliencelab benchmark RL-BENCH-005 --repetitions 5
```

Configs live in `benchmarks/` and are ordinary experiment files, so any
benchmark can be edited, validated, and reproduced like any other experiment.
