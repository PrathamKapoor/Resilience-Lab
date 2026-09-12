"""Statistical and comparative analysis of experiment results."""

from resiliencelab.analysis.comparison import (
    PRIMARY_METRICS,
    aggregate_metric,
    build_comparison,
)
from resiliencelab.analysis.interactions import interaction_with_uncertainty, two_way_interaction
from resiliencelab.analysis.recovery import RecoveryReport, detect_recovery
from resiliencelab.analysis.scoring import DEFAULT_WEIGHTS, ResilienceScore, compute_score
from resiliencelab.analysis.statistics import (
    bootstrap_ci,
    cohens_d,
    mean_ci,
    summarize,
    welch_ttest,
)

__all__ = [
    "DEFAULT_WEIGHTS",
    "PRIMARY_METRICS",
    "RecoveryReport",
    "ResilienceScore",
    "aggregate_metric",
    "bootstrap_ci",
    "build_comparison",
    "cohens_d",
    "compute_score",
    "detect_recovery",
    "interaction_with_uncertainty",
    "mean_ci",
    "summarize",
    "two_way_interaction",
    "welch_ttest",
]
