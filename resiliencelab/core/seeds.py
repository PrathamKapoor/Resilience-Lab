"""Deterministic random-number handling for reproducible experiments."""

from __future__ import annotations

from numpy.random import Generator, SeedSequence, default_rng


def generator(seed: int | None = None) -> Generator:
    return default_rng(seed)


def generator_for(seed: int, *keys: int) -> Generator:
    return default_rng(SeedSequence([seed, *keys]))


def spawn(seed: int, count: int) -> list[Generator]:
    children = SeedSequence(seed).spawn(count)
    return [default_rng(child) for child in children]
