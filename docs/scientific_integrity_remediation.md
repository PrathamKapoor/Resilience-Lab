# Scientific Integrity Remediation — baseline and plan

Baseline commit: `060ee1d` (one commit ahead of release-candidate `934d554`; audit worktree at `934d554` preserved separately).
Baseline quality gates: `ruff check` clean, `ruff format --check` clean, `mypy resiliencelab` strict clean.
Baseline tests: 434 collected, 433 passed, 1 skipped (Windows `pytest-current` symlink cleanup `PermissionError` on session finish is environmental, not a test failure).
Benchmarks: 18 YAMLs (`RL-BENCH-001..018`).
Artifact integrity: SHA256 manifest + `verify_artifacts` exists; checks hashes only.
Reproduction: `reproduce <id>` exists; `reproduce --all` does not exist; `make reproduce-paper` at `934d554` invoked missing `--all`.

## Status: all CRITICAL remediated, HIGHs fixed or documented with tests

- C1 DONE: hierarchical `results/<base>/conditions/<condition_id>/` (`experiments/matrix.py` + CLI),
  `condition.json` provenance, `matrix_manifest.json`, comparison entries reference persisted dirs.
  End-to-end verified on an RL-BENCH-017-derived topology (4 conditions, full bundles, valid manifests).
- C2 DONE: `reproduce --all` with discovery, per-benchmark rerun+verify, `reproduction_manifest.json`,
  non-zero exit on failure; Makefile/paper/reproduce.md/outline describe the same workflow; no fake figures.
- C3 DONE: Layer A/B/C defined in `docs/reproducibility.md`, referenced by README/simulation/workloads/
  outline/report; `tests/test_determinism_layers.py` pins decision determinism vs wall-clock variance.
- C4 DONE: `experiments/catalog.py` (YAML-derived + hypothesis/RQ/metrics/factors/status) with
  `tests/test_benchmark_catalog.py` failing CI on duplicates/malformed/count drift/missing paper IDs.
- C5 DONE: latency gate implemented (throughput AND latency sustained for W), gates persisted
  (`gates_evaluated`, `latency_gate`, `latency_degraded/recovered`); hidden `latency_ratio=2.0`
  multiplier corrected to documented `1.0` default; 5 gate tests.
- HIGHs DONE: censored recovery stats (`summarize_censored`, no nan CIs, wired into artifacts/report);
  spec confidence passthrough; lib-level seed-divergence pairing warning; integrity-vs-correctness docs;
  n=5 power/interaction/Holm-default docs; RQ answerability matrix; capability downgrades
  (`connect`, `endpoint_mix`, RL-004/006/013-014 notes).
- Extra root-cause finds during verification (all fixed + tested): nullable-intermediate crash in
  `design._set_path` with `CORE_FACTORS` on timeout-less bases; `matrix` crash on dict factor levels
  (`unhashable type: 'dict'` — default CORE_FACTORS path never completed effects); raw pydantic
  `ValidationError` escaping `load_yaml`/`parse_experiment` instead of `ConfigValidationError`.


Audit scope verified against source at `934d554` (read-only worktree + `python -c` probes; no code changed during audit):

- C1 matrix collision: REPRODUCED. `cli/app.py matrix` uses `build_design` (ids preserved) then `store/<base-id>` per condition; probe with `CORE_FACTORS` gives 64 conditions sharing one spec id.
- C2 reproduce-paper: REPRODUCED. `Makefile reproduce-paper` → `reproduce --all`; CLI has no `--all`.
- C3 wall-clock dominance: REPRODUCED. Same seed/config `closed_loop` 1s runs gave totals 3030/2790 and availability 0.807/0.649; repeat gave 2800/0.651, 2950/0.622, 2430/0.683. Clocks/sleeps/deadlines/queue/fault windows are wall-clock (`clock.py`, `generator.py`, `dependency.py`, `capacity.py`).
- C4 catalog mismatch: REPRODUCED. `docs/benchmarks.md` RL-017 `timeout-cascade` vs YAML `policy-by-fault-factorial`; README/outline/layout counts disagree (016/008/012 vs actual 018).
- C5 recovery latency gate: REPRODUCED at `934d554`. `detect_recovery` accepts `latency_series` but never reads it; throughput-only recovery returned `recovered_at=6.0` with p95 100x baseline.
- C6 inf recovery stats: REPRODUCED. `summarize([inf,5,6])` → `mean=inf, CI=[nan,nan]`; report renders `mean=inf, 95% CI [nan, nan]`.
- H-series spot-checked: all benchmarks `closed_loop`; `connect` timeout schema-only; `payload_size` unwired; `endpoint_mix` label-only vs stale doc; `RL-BENCH-004` saturation fault without service capacity; `_build_statistics` hardcodes 0.95/t-only; paired comparison pairs by index regardless of seeds; `verify_artifacts` integrity-only with warn-only extras and unsigned manifest.

Plan (root-cause fixes, regression tests, honest docs; no new infra):

- C1: hierarchical `results/<base>/conditions/<condition_id>/` + matrix manifest referencing persisted artifacts; tests for 64 namespaces, determinism, rerun isolation, manifest validity, cancelled handling.
- C2: implement `reproduce --all` with discovery, per-experiment rerun+verify, machine-readable manifest, non-zero exit on failure; align Makefile/CLI/paper/reproduce.md; tests for help/success/missing/corrupt/partial/exit/manifest/determinism.
- C3: define Layer A (seeded decisions) / B (wall-clock execution) / C (artifact provenance); update README/reproducibility/simulation/workloads/outline/report text; tests for decision determinism and wall-clock variance allowance.
- C4: authoritative `experiments/catalog.py` derived from YAMLs + RQ mapping; fix README/docs/outline agreement; CI test failing on duplicates/malformed/count drift/missing paper IDs.
- C5: implement documented latency gate (throughput AND latency sustained for stability window), persist gates; tests for 4 required cases. Remove hidden `latency_ratio` multiplier or document/persist it explicitly.
- HIGHs: censored recovery stats (no nan CIs); n=5 power limitation docs; seed-mismatch pairing warning; integrity-vs-correctness docs; RQ answerability matrix (RQ8 future, RQ6 limited); bootstrap wiring docs + confidence passthrough; capability downgrades (`connect`, `payload_size`, `endpoint_mix`, RL-004/006 wording).
