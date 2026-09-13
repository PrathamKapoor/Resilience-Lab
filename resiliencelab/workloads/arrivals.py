"""Workload arrival processes: pure, seeded inter-arrival gap computation.

A closed-loop workload is client-driven (see ``generator.py``); every other
workload type is an *arrival process*: a rule that, given the elapsed time
since the workload began and a seeded pseudo-random generator, returns the
next inter-arrival gap in seconds.

Keeping gap computation a pure function of ``(elapsed, rng)`` — plus minimal
internal state for bursts — makes the traffic semantics explicit and unit
testable while leaving the actual wall-clock scheduling (``asyncio.sleep``)
to the generator. Stochastic decisions are seeded and therefore reproducible;
wall-clock completion times are not.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from resiliencelab.core.schema import ArrivalDistribution, WorkloadSpec, WorkloadType

if TYPE_CHECKING:
    from numpy.random import Generator

_MIN_RATE = 1e-3

_RAMP_START_FRACTION = 0.1


class ArrivalModel:
    """Computes the next inter-arrival gap for a non-closed-loop workload."""

    def __init__(self, spec: WorkloadSpec) -> None:
        self.spec = spec
        self._burst_remaining = spec.burst_size - 1

    def gap(self, elapsed: float, rng: Generator) -> float:
        spec = self.spec
        rate = float(spec.arrival_rate)
        mode = spec.type
        if mode is WorkloadType.CLOSED_LOOP:
            raise ValueError("closed_loop is client-driven and has no arrival model")
        if mode is WorkloadType.CONSTANT_RATE:
            return 1.0 / rate
        if mode is WorkloadType.OPEN_LOOP:
            return self._distributed_gap(rng, rate)
        if mode is WorkloadType.RANDOM:
            return float(rng.uniform(0.0, 2.0 / rate))
        if mode is WorkloadType.BURST:
            return self._burst_gap(rate)
        if mode is WorkloadType.PERIODIC:
            return self._periodic_gap(elapsed, rate)
        if mode is WorkloadType.RAMP:
            return self._ramp_gap(elapsed, rate)
        raise ValueError(f"unsupported workload type: {mode.value}")

    def _distributed_gap(self, rng: Generator, rate: float) -> float:
        distribution = self.spec.distribution
        if distribution is ArrivalDistribution.CONSTANT:
            return 1.0 / rate
        return float(rng.exponential(1.0 / rate))

    def _burst_gap(self, rate: float) -> float:
        if self._burst_remaining > 0:
            self._burst_remaining -= 1
            return 1.0 / rate
        self._burst_remaining = self.spec.burst_size - 1
        return float(self.spec.burst_interval)

    def _periodic_gap(self, elapsed: float, rate: float) -> float:
        period = max(float(self.spec.period), 1e-6)
        amplitude = float(self.spec.burstiness)
        rate_t = rate * (1.0 + amplitude * math.sin(2.0 * math.pi * elapsed / period))
        return 1.0 / max(rate_t, rate * _MIN_RATE)

    def _ramp_gap(self, elapsed: float, rate: float) -> float:
        duration = max(float(self.spec.duration), 1e-6)
        progress = min(1.0, elapsed / duration)
        rate_t = max(
            rate * (_RAMP_START_FRACTION + (1.0 - _RAMP_START_FRACTION) * progress), _MIN_RATE
        )
        return 1.0 / rate_t
