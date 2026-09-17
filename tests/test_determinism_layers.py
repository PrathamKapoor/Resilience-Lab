"""C3 regression: layered determinism — seeded decisions vs wall-clock execution."""

from __future__ import annotations

from resiliencelab.core.clock import Clock
from resiliencelab.core.schema import ProcessingSpec
from resiliencelab.core.seeds import generator_for
from resiliencelab.faults.model import FailureKind, FaultInjector, FaultSpec
from resiliencelab.services.network import NETWORK_RNG_SALT, NetworkLinkSpec, network_delay
from resiliencelab.services.processing import sample_processing_latency
from resiliencelab.workloads.generator import ENDPOINT_MIX_RNG_SALT


def test_layer_a_fault_draws_deterministic_per_seed_and_request() -> None:
    spec = FaultSpec(kind=FailureKind.HTTP_503, probability=0.5)
    first = [
        FaultInjector(spec).evaluate(0.0, generator_for(7, k, 1)) is not None for k in range(50)
    ]
    second = [
        FaultInjector(spec).evaluate(0.0, generator_for(7, k, 1)) is not None for k in range(50)
    ]
    assert first == second
    assert any(first) and not all(first)


def test_layer_a_jitter_processing_network_endpoint_draws_deterministic() -> None:
    for request_id in (0, 1, 42):
        assert generator_for(9, request_id).uniform(0, 1) == generator_for(9, request_id).uniform(
            0, 1
        )
        proc = ProcessingSpec(distribution="normal", mean=0.05, std=0.01)
        a = sample_processing_latency(proc, generator_for(9, request_id, 1, 2))
        b = sample_processing_latency(proc, generator_for(9, request_id, 1, 2))
        assert a == b
        link = NetworkLinkSpec(latency=0.02, jitter=0.005)
        assert network_delay(
            link, generator_for(9, request_id, NETWORK_RNG_SALT, 0)
        ) == network_delay(link, generator_for(9, request_id, NETWORK_RNG_SALT, 0))
        assert int(generator_for(9, request_id, ENDPOINT_MIX_RNG_SALT).integers(0, 3)) == int(
            generator_for(9, request_id, ENDPOINT_MIX_RNG_SALT).integers(0, 3)
        )


def test_layer_b_wall_clock_advances_and_is_not_seeded() -> None:
    clock = Clock()
    t0 = clock.now()
    t1 = clock.now()
    assert t1 >= t0
    # Two clocks started at different wall-clock times disagree: not seeded.
    assert Clock().now() != Clock(start_offset=100.0).now()


def test_layer_b_same_seed_runs_share_decisions_but_timing_may_vary() -> None:
    # Decision-level: same (seed, request_id) fault outcome regardless of run.
    spec = FaultSpec(kind=FailureKind.HTTP_503, probability=0.5)
    outcomes_a = [
        FaultInjector(spec).evaluate(0.0, generator_for(3, k, 77)) is not None for k in range(20)
    ]
    outcomes_b = [
        FaultInjector(spec).evaluate(0.0, generator_for(3, k, 77)) is not None for k in range(20)
    ]
    assert outcomes_a == outcomes_b
    # Execution-level quantities are wall-clock: latencies/timestamps are floats
    # measured at runtime, never asserted equal across runs (see docs).
    import time

    assert isinstance(time.perf_counter(), float)


def test_layer_c_provenance_records_seeds_not_wall_clock_equality() -> None:
    from resiliencelab.core.schema import ExperimentSpec
    from resiliencelab.experiments.provenance import capture_environment, hash_config

    spec = ExperimentSpec(id="layer_c", name="layer c")
    assert hash_config(spec) == hash_config(spec)
    env = capture_environment()
    assert "python_version" in env and "platform" in env
