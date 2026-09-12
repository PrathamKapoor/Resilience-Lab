# Research paper outline

## Working title

*ResilienceLab: A Reproducible Benchmarking Platform for Distributed-Service
Resilience Policies*

## Claims (to be evidenced, not assumed)

1. A reproducible experimental framework for resilience evaluation.
2. A controlled fault-model taxonomy (errors, latency, connection, saturation,
   temporal modes).
3. A standardized benchmark suite (RL-BENCH-001..008).
4. Systematic evaluation of retry, backoff, jitter, circuit breaking,
   concurrency limiting, and timeouts — individually and combined.
5. Empirical analysis of mechanism interactions and failure amplification.
6. Recovery characterization with explicit, configurable definitions.

## Research questions

RQ1 individual mechanisms · RQ2 failure-type sensitivity · RQ3 interaction
effects · RQ4 failure amplification · RQ5 recovery · RQ6 workload sensitivity ·
RQ7 trade-offs · RQ8 adaptation (future work: adaptive controllers).

## Method

For each benchmark × policy × workload cell: N deterministic-seed repetitions,
workload with warmup excluded from measurement, per-bucket timeline, bootstrap
confidence intervals, effect sizes with multiple-comparison awareness, and
hashed immutable artifacts per run.

## Threats to validity

- Internal: shared in-process clock and event loop; mitigated by per-request
  seeded randomness and warmup exclusion.
- External: single-node FastAPI services, not a geo-distributed mesh; results
  generalize as mechanism behavior, not absolute numbers.
- Construct: recovery defined by explicit thresholds recorded per experiment.
- Statistical: repetition counts and CIs reported; no best-run reporting.
- Infrastructure: container scheduling and noisy neighbors affect tail
  latency; report hardware and environment capture with every result.

## Reproduction

```bash
make reproduce-paper
```

regenerates figures and tables from stored artifacts (see `paper/reproduce.md`).
