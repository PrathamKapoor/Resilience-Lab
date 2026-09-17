# Statistical Design and Analysis — ResilienceLab

## 1. Experimental Unit

The fundamental scientific unit in ResilienceLab is the **seeded repetition** (run), not the individual request.

If an experiment runs with:

```text
repetitions = 5
clients = 50
duration = 40s
```

the 5 repetitions are the independent experimental replicates. The thousands of requests produced inside each repetition are **not** independent observations for inferential statistics. Treating them as such would create pseudo-replication and falsely inflate statistical precision.

Every statistical observation in this system traces back to:

```text
experiment_id → run_id → repetition → seed
```

The analysis layer (`resiliencelab/analysis/`) operates exclusively on repetition-level metrics (`metrics_per_run`) unless a different unit is explicitly configured.

## 2. Replicate Identity and Pairing

Paired comparisons are valid only when two conditions share a **matched replicate identity**.

For the factorial design (`analysis/design.py`), conditions are expanded deterministically and replicate seeds are assigned deterministically (`base_seed + index` for deterministic strategy). This means replicate index `i` in condition A and replicate index `i` in condition B experience comparable stochastic conditions.

Paired analysis uses:

```text
D_i = A_i - B_i
```

and estimates the mean paired difference, median paired difference, and a confidence interval over the paired differences (`paired_difference_summary` in `analysis/statistics.py`).

Unbalanced replicates (different `n`) are handled by pairing only the first `min(n_A, n_B)` replicates, with an explicit warning (`build_paired_comparison` in `analysis/comparison.py`).

## 3. Factorial Design

The design layer (`analysis/design.py`) provides deterministic full-factorial expansion via `build_design`. Given base factors, it produces a stable, hash-identified condition for every combination (`DesignCondition`).

Condition identity (`condition_id`) is derived from a SHA-256 hash of the base experiment ID and the assigned factor values, not from dictionary iteration order. Changing any factor value changes the identity.

Supported analyses:

- **Main effects** (`main_effect`): per-level mean and deviation from grand mean for a single factor.
- **Two-way interaction** (`interaction_effect`): difference-of-differences estimate for binary factors (`A1B1 - A0B1 - (A1B0 - A0B0)`).
- **Interaction with uncertainty** (`interaction_with_uncertainty`): bootstrap-based confidence interval over resampled cell means. The bootstrap uses a fixed `rng = np.random.default_rng(0)` for determinism.

## 4. Confidence Intervals

Confidence intervals are computed using the student-t method (`mean_ci` in `analysis/statistics.py`) for the mean of repetition-level observations:

```text
mean ± t_(1-α/2, n-1) * (s / sqrt(n))
```

Default CIs are t-based; `bootstrap_ci` is available opt-in (`aggregate_metric(use_bootstrap=True)`,
`interaction_with_uncertainty`) and is NOT the default in artifacts, `compare`, or `matrix`.
Artifact statistics record the configured `confidence_level` from the experiment spec.

### Small-n behavior and power

The system never reports false precision for very small samples:

- `n < 2`: describes statistics only; no inferential CI or effect size is produced (`small_sample_note`).
- `n < 5`: reports a cautionary note (`"highly uncertain"`).
- `n = 5` (most benchmarks): t-intervals use `t=2.776 (df=4)` — wide by
  construction, with low power for medium effects. Treat "overlapping CIs"
  reproduction checks as weak evidence and non-overlap as suggestive, not proof.
  Two-way interactions split n further across cells.

Every statistical output includes `n` (repetition count) explicitly (`aggregate_metric`, `build_report`).

## 5. Bootstrap and Determinism

Bootstrap resampling is reproducible: the same inputs with the same analysis configuration produce identical results. The bootstrap seed is fixed (`rng = np.random.default_rng(0)`) unless an external `rng` is explicitly passed.

Two analyses of the same manifest-hashed artifact (`analysis_version`, same conditions, same seeds, same observations) must produce the same statistical result. This is verified by `test_bootstrap_is_deterministic_given_fixed_inputs` (`tests/test_statistics_anti_leakage.py`).

## 6. Effect Sizes

Effect size methods are documented and tested:

- **Cohen's d (independent)** (`cohens_d`): pooled standard deviation for independent groups.
- **Cohen's d (paired)** (`cohens_d_paired`): `mean(D) / SD(D)` over paired replicate differences.

Effect sizes are reported only when `n >= 2` for the compared groups.

## 7. Multiple Comparisons

For family-wise comparisons across factorial conditions, Holm-Bonferroni step-down correction (`holm_adjust`) is available. The comparison family is defined as all pairwise metric comparisons performed in a single `build_comparison` invocation.

Correction is not automatically applied to all outputs; it is applied where explicitly configured (`analysis_version` and comparison artifacts must document the correction method used, if any).
Default `compare`/`matrix` outputs are uncorrected across the 9 primary metrics.

## 8. Pareto / Trade-off Analysis

`pareto_frontier` (`analysis/statistics.py`) identifies non-dominated configurations for a selected set of objectives. A point is dominated only when another point is:

- no worse on every objective, and
- strictly better on at least one objective

Objectives must specify direction (`True` = higher is better, `False` = lower is better). The output is a list of indices into the input point list.

The CLI `compare` command and `matrix` output do not assign arbitrary weights; weights are only applied when an explicit `ResilienceScore` (`analysis/scoring.py`) is computed by user choice.

## 9. Recovery Analysis

Recovery is defined explicitly in `analysis/recovery.py` (`detect_recovery`).
All evaluated gates must hold for the continuous stability window W:

```text
throughput ≥ availability_threshold × baseline  AND  (when latency data exists)
p95 ≤ baseline_p95 × (1 + latency_tolerance) × latency_ratio  (latency_ratio = 1.0 by default)
```

The report persists `gates_evaluated` (`["throughput"]` or
`["throughput", "latency"]`), `baseline_p95_latency`, `latency_gate`,
`latency_degraded`, and `latency_recovered` alongside the timing fields.

Recovery statistics (`time_to_degradation`, `degraded_duration`, `time_to_recovery`) are reported per repetition and aggregated across repetitions. Unrecovered conditions are represented as `inf` (censored/unrecovered), not as zero recovery time. Aggregations over `recovery_time` use censored statistics (recovery rate plus summaries over recovered runs) so a single `inf` cannot poison a mean/CI into `nan`.

Repeated recovery statistics are included in `ExperimentResult.as_comparison_entry()` and in artifacts (`metrics_per_run`).

## 10. Failure Amplification

Amplification is preserved as a first-class metric (`amplification`). For retry experiments, the interaction with service capacity is quantified explicitly (`interaction_effect` and `main_effect`) to detect when retries improve availability versus when they amplify saturation.

## 11. Statistical Result Schema

`StatisticalResult` (`analysis/statistics.py`) provides a structured, serializable representation with fields:

- `metric`, `estimate`, `n`, `method`, `confidence_level`
- `ci_low`, `ci_high`
- `paired` (boolean), `reference`, `difference`, `effect_size`
- `resampling_unit`, `warnings`, `analysis_version`

Every field that is not meaningful for a given analysis may remain empty (`None`). The schema is versioned (`STAT_ANALYSIS_VERSION = "2"`).

## 12. Artifact Provenance

Every statistical artifact (`analysis/statistics.json`, comparison artifacts, matrix artifacts) records:

```text
analysis_version
design_id / condition_id
repetitions / seeds
metric
statistical_method (e.g., t_mean_ci)
confidence_level
resampling_method (e.g., bootstrap)
resampling_unit (always "repetition" for experiment-level inference)
effect_size_method
effect_size (if applicable)
multiple_comparison_method (if applied)
```

The artifact manifest (`manifest.json`) links all files by cryptographic hash, enabling future researchers to reproduce the exact statistical pipeline from raw observations.

## 13. Limitations and Scope

- Only two-factor interactions are fully implemented (`interaction_effect`). Arbitrary multi-factor ANOVA or GLM frameworks are not included; adding them without proper validation would risk statistical misleadingness.
- Paired designs assume that replicate index `i` corresponds to the same stochastic conditions across conditions (deterministic seed assignment ensures this for the base design). Pairing by index when recorded seeds differ emits an explicit warning; such comparisons are not valid paired evidence.
- `interaction_with_uncertainty` resamples cells independently and does not preserve pairing; use it for independent-cell uncertainty only.
- Default `build_comparison` effect sizes are independent-group Cohen's d even when conditions share seeds; use `build_paired_comparison` (paired d) for matched designs.
- Bootstrap intervals assume independent repetition-level observations. They do not model temporal autocorrelation within a single repetition.
- Small samples (`n < 5`) produce highly uncertain intervals; `n = 5` intervals remain wide (see §4). The system reports this explicitly rather than suppressing it.

## 14. Anti-Leakage Guarantees

Critical scientific mistakes are caught by dedicated tests (`tests/test_statistics_anti_leakage.py`):

- **Pseudo-replication**: statistics use repetition count, not request count.
- **Pairing mismatch**: unbalanced replicates trigger a warning; seed-divergent
  pairings trigger a warning; silent pairing of mismatched conditions is prevented.
- **Bootstrap determinism**: identical inputs produce identical results.
- **Condition contamination**: observations from one factorial cell cannot enter another.
- **Seed provenance**: every statistical observation references its source `run_id` / `seed`.
