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

Run one with:

```bash
resiliencelab benchmark RL-BENCH-005 --repetitions 5
```

Configs live in `benchmarks/` and are ordinary experiment files, so any
benchmark can be edited, validated, and reproduced like any other experiment.
