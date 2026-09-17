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
| RL-BENCH-017 | policy-by-fault-factorial | Full-factorial design measuring policy main effects and policy x fault interactions |
| RL-BENCH-018 | retry-by-capacity-factorial | Full-factorial design quantifying when retries improve availability |

Run one with:

```bash
resiliencelab benchmark RL-BENCH-005 --repetitions 5
```

Configs live in `benchmarks/` and are ordinary experiment files, so any
benchmark can be edited, validated, and reproduced like any other experiment.

The authoritative research mapping (hypothesis, research questions, expected
metrics, factorial factors, status) lives in
`resiliencelab/experiments/catalog.py` and is derived mechanically from the
YAMLs; `tests/test_benchmark_catalog.py` fails CI on duplicates, malformed
YAMLs, count drift, or missing paper IDs.

Notes:

- RL-BENCH-017 and RL-BENCH-018 are single-cell **base configs** for factorial
  analysis, not expanded factorial designs by themselves. Run `matrix` to
  expand factors; per-condition bundles land under
  `results/<base-id>/conditions/<condition_id>/`.
- RL-BENCH-004 exercises client-side concurrency plus the saturation-delay
  fault, not service-side capacity (which has no block in that YAML).
- RL-BENCH-006 short-circuits on the first failure, sparing downstream
  services; "cascade" here means staged short-circuit, not propagation.
- RL-BENCH-013/014 isolation is observable at event/service level; primary
  comparison metrics remain global.
- All 18 benchmarks use `closed_loop` workloads; RQ6 workload sensitivity is
  therefore limited (see `paper/outline.md`).
