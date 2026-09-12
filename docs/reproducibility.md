# Reproducibility

Every `resiliencelab run` writes an artifact bundle:

```text
results/<experiment-id>/
  configuration.yaml
  environment.json
  experiment.json
  raw/records-<i>.jsonl
  raw/records-hash.txt
  analysis/statistics.json
  analysis/summary.json
  analysis/timeline-<i>.json
  report/report.md
  manifest.json
```

Guarantees and limits:

- `manifest.json` records SHA256 hashes of every file plus the configuration
  hash and raw-records hash.
- `resiliencelab reproduce <id>` reloads `configuration.yaml`, reruns with the
  recorded seeds, and stores the new bundle for comparison.
- Randomness is derived per request from `(seed, request_id)`, so identical
  seeds give identical fault decisions and jitter draws.
- Exact timing (throughput, latencies) varies with hardware and scheduling;
  reproduction is therefore *statistically consistent* (overlapping confidence
  intervals), not bit-identical. Compare `analysis/statistics.json` across
  bundles to verify.
