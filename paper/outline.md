# Research paper outline

## Working title

*ResilienceLab: A Reproducible Benchmarking Platform for Distributed-Service
Resilience Policies*

## Claims (to be evidenced, not assumed)

1. A reproducible experimental framework for resilience evaluation.
2. A controlled fault-model taxonomy (errors, latency, connection, saturation,
   temporal modes).
3. A standardized benchmark suite (RL-BENCH-001..018).
4. Systematic evaluation of retry, backoff, jitter, circuit breaking,
   concurrency limiting, and timeouts — individually and combined.
5. Empirical analysis of mechanism interactions and failure amplification.
6. Recovery characterization with explicit, configurable definitions.

## Research questions

RQ1 individual mechanisms · RQ2 failure-type sensitivity · RQ3 interaction
effects (two-way only) · RQ4 failure amplification · RQ5 recovery ·
RQ6 workload sensitivity (limited: suite is closed-loop; other modes available
but unbenchmarked) · RQ7 trade-offs (Pareto; composite weights user-chosen) ·
RQ8 adaptation (future work: no adaptive controllers implemented).

## Answerability

| RQ | Status | Evidence |
|----|--------|----------|
| RQ1 | answerable | single-mechanism benchmarks 001-004, 009-011 |
| RQ2 | answerable | error/latency/saturation benchmarks 001, 002, 008 |
| RQ3 | partially (two-way binary only) | factorial design + 017/018 base configs |
| RQ4 | answerable | amplification benchmarks 005, 012 |
| RQ5 | answerable | recovery benchmarks 003, 007, 016 |
| RQ6 | limited | all benchmarks closed-loop; open-loop modes exist but lack benchmark coverage |
| RQ7 | partially (weights exposed, not principled) | scoring + Pareto |
| RQ8 | not implemented (future work) | no adaptive controllers exist |

## Method

For each benchmark × policy × workload cell: seeded repetitions (seeded
decisions deterministic per Layer A; wall-clock execution varies per Layer B —
see `docs/reproducibility.md`), workload with warmup excluded from measurement,
per-bucket timeline, t-based confidence intervals over repetitions (bootstrap
available opt-in), effect sizes with multiple-comparison awareness, and hashed
artifact bundles per run (integrity, not correctness).

## Threats to validity

- Internal: shared in-process clock and event loop; mitigated by per-request
  seeded randomness and warmup exclusion.
- External: single-node FastAPI services, not a geo-distributed mesh; results
  generalize as mechanism behavior, not absolute numbers.
- Construct: recovery defined by explicit thresholds recorded per experiment.
- Statistical: repetition counts and CIs reported; no best-run reporting.
  n=5 (most benchmarks) gives wide t-intervals (t=2.776, df=4) and low power
  for medium effects; interactions split n further; Holm available but opt-in.
- Infrastructure: container scheduling and noisy neighbors affect tail
  latency; report hardware and environment capture with every result.
  Same-seed reruns may differ in counts/throughput/recovery (Layer B).

## Reproduction

```bash
make reproduce-paper
# equivalent: resiliencelab reproduce --all --store ./results
```

reruns declared benchmarks, verifies bundles, and writes
`results/reproduction_manifest.json` (see `paper/reproduce.md`). No
figure/table generation exists yet.
