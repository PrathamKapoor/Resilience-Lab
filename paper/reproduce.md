# Reproducing the paper artifacts

1. Install dependencies: `python -m pip install -e ".[dev,parquet]"`.
2. Run the benchmark matrix (see `benchmarks/` and `resiliencelab matrix`).
3. Each run stores hashed artifacts under `results/<experiment-id>/`.
4. Aggregate with `analysis/comparison.py` and `analysis/interactions.py`.
5. Regenerate figures/tables from `analysis/statistics.json` files.

`make reproduce-paper` runs the CLI reproduction flow for stored experiments.
