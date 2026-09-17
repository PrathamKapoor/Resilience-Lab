"""C4 regression: the benchmark catalog must be authoritative and consistent."""

from __future__ import annotations

from pathlib import Path

from resiliencelab.experiments.benchmarks import STANDARD_BENCHMARKS, list_standard_benchmarks
from resiliencelab.experiments.catalog import (
    PAPER_BENCHMARK_IDS,
    load_catalog,
    validate_catalog,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_catalog_loads_18_benchmarks() -> None:
    entries = load_catalog(_repo_root() / "benchmarks")
    assert len(entries) == 18
    assert sorted(e["id"] for e in entries) == sorted(STANDARD_BENCHMARKS)


def test_catalog_validation_passes() -> None:
    entries = load_catalog(_repo_root() / "benchmarks")
    assert validate_catalog(entries) == []


def test_every_benchmark_has_hypothesis_and_rq_mapping() -> None:
    entries = load_catalog(_repo_root() / "benchmarks")
    for entry in entries:
        assert entry["hypothesis"], entry["id"]
        assert entry["research_questions"], entry["id"]


def test_standard_list_matches_catalog_files() -> None:
    assert sorted(list_standard_benchmarks()) == sorted(PAPER_BENCHMARK_IDS)
    entries = load_catalog(_repo_root() / "benchmarks")
    assert {e["id"] for e in entries} == set(STANDARD_BENCHMARKS)


def test_docs_benchmark_table_matches_catalog() -> None:
    text = (_repo_root() / "docs" / "benchmarks.md").read_text(encoding="utf-8")
    entries = load_catalog(_repo_root() / "benchmarks")
    for entry in entries:
        assert entry["id"] in text, entry["id"]
        assert entry["name"] in text, entry["id"]


def test_readme_and_outline_counts_match_catalog() -> None:
    entries = load_catalog(_repo_root() / "benchmarks")
    readme = (_repo_root() / "README.md").read_text(encoding="utf-8")
    outline = (_repo_root() / "paper" / "outline.md").read_text(encoding="utf-8")
    assert "RL-BENCH-001..018" in readme
    assert "RL-BENCH-001..018" in outline
    assert len(entries) == 18


def test_no_duplicate_ids_or_malformed_yaml() -> None:
    entries = load_catalog(_repo_root() / "benchmarks")
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == len(ids)
    for entry in entries:
        assert entry["repetitions"] >= 1
        assert entry["workload"]
