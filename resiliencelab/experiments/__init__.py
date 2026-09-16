"""Experiment execution, provenance, registry, factorial generation, and result types."""

from resiliencelab.experiments.artifacts import verify_artifacts, write_artifacts
from resiliencelab.experiments.factorial import CORE_FACTORS, generate_matrix
from resiliencelab.experiments.provenance import (
    canonical_config,
    capture_environment,
    hash_config,
    hash_records,
)
from resiliencelab.experiments.registry import ExperimentRegistry
from resiliencelab.experiments.report import automatic_analysis, build_report
from resiliencelab.experiments.result import ExperimentResult, RunResult
from resiliencelab.experiments.runner import ExperimentRunner

__all__ = [
    "CORE_FACTORS",
    "ExperimentRegistry",
    "ExperimentResult",
    "ExperimentRunner",
    "RunResult",
    "automatic_analysis",
    "build_report",
    "canonical_config",
    "capture_environment",
    "generate_matrix",
    "hash_config",
    "hash_records",
    "write_artifacts",
    "verify_artifacts",
]
