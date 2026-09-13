"""Benchmark suite resolution and loading."""

from __future__ import annotations

from pathlib import Path

STANDARD_BENCHMARKS = [
    "RL-BENCH-001",
    "RL-BENCH-002",
    "RL-BENCH-003",
    "RL-BENCH-004",
    "RL-BENCH-005",
    "RL-BENCH-006",
    "RL-BENCH-007",
    "RL-BENCH-008",
    "RL-BENCH-009",
    "RL-BENCH-010",
    "RL-BENCH-011",
    "RL-BENCH-012",
]


def normalize_benchmark_name(name: str) -> str:
    text = name.upper().strip()
    if text.startswith("RL-BENCH-"):
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return f"RL-BENCH-{int(digits):03d}"
    return text


def resolve_benchmark_path(name: str, benchmarks_dir: str | None = None) -> Path | None:
    candidates = [
        Path(benchmarks_dir) / f"{name}.yaml" if benchmarks_dir else None,
        Path("benchmarks") / f"{name}.yaml",
        Path("configs") / "benchmarks" / f"{name}.yaml",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return candidate
    return None


def list_standard_benchmarks() -> list[str]:
    return list(STANDARD_BENCHMARKS)
