# Reproducing the paper artifacts

1. Install dependencies: `python -m pip install -e ".[dev,parquet]"`.
2. Reproduce all declared benchmarks (see `benchmarks/` and `resiliencelab reproduce --all`):

   ```bash
   make reproduce-paper
   # equivalent: resiliencelab reproduce --all --store ./results
   ```

   Each benchmark reruns from its YAML, stores a hashed artifact bundle under
   `results/<experiment-id>/`, verifies it against `manifest.json`, and appends
   one entry to `results/reproduction_manifest.json`. The command exits non-zero
   if any benchmark is missing, fails, or fails verification.
3. Factorial matrices store per-condition bundles under
   `results/<base-id>/conditions/<condition_id>/` plus `matrix_design.json`,
   `matrix_comparison.json`, `matrix_effects.json`, and `matrix_manifest.json`.
4. Aggregate with `analysis/comparison.py` and `analysis/interactions.py`;
   per-run statistics live in each bundle's `analysis/statistics.json`.

No figure/table generation code exists yet; reproduction produces verified
artifacts and statistical summaries, not PDF figures. `paper/outline.md`
describes the same workflow.

Full reproduction runs all 18 benchmarks at their declared repetitions
(typically 5 x 20-40s each) and can take tens of minutes. For a fast smoke
test of the workflow, override the repetition count:

```bash
resiliencelab reproduce --all --store ./results --repetitions 1
```

Smoke runs validate the pipeline (resolution, execution, artifacts,
verification, manifest) but their confidence intervals carry the small-n
limits documented in `docs/statistics.md`.
