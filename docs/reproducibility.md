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
  hash and raw-records hash. Verification checks integrity (hashes match),
  not scientific correctness. The manifest is unsigned and untracked files
  warn rather than fail; treat verification as tamper-evidence, not proof.
- `resiliencelab reproduce <id>` reloads `configuration.yaml`, reruns with the
  recorded seeds, and stores the new bundle for comparison.
- `resiliencelab reproduce --all` reruns every declared benchmark, verifies
  each bundle, and writes `results/reproduction_manifest.json` (non-zero exit
  if any benchmark is missing, fails, or fails verification).
- Reproducibility has three layers:
  - **Layer A — seeded decisions (deterministic).** Same configuration + seed
    gives identical fault draws, jitter draws, processing/network draws, and
    endpoint routing for the same `request_id` (see `core/seeds.py`).
  - **Layer B — wall-clock execution (varies).** Request counts, throughput,
    queue waits, deadline-boundary timeouts, recovery times, and measured
    latencies depend on real scheduling and may differ across same-seed runs.
    Same seed does NOT imply identical complete metrics.
  - **Layer C — artifact provenance (recorded).** Configuration, seeds,
    environment, statistical method/version, and hashes are recorded so a
    later researcher can reconstruct the exact pipeline and compare
    `analysis/statistics.json` across bundles (overlapping confidence
    intervals), not bit-identical metrics.
