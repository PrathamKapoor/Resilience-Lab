"""Simulated inter-service network latency and jitter.

Network delay is a simulated, seeded quantity applied on the caller→dependency
edge before queueing and service processing. It is not a measurement of any
real network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resiliencelab.core.schema import NetworkLinkSpec, NetworkSpec

if TYPE_CHECKING:
    from numpy.random import Generator

NETWORK_RNG_SALT = 0x4E57


def resolve_network_link(
    network: NetworkSpec | None,
    source: str,
    target: str,
) -> NetworkLinkSpec | None:
    """Resolve the network link for a source→target edge.

    A matching ``edges`` entry wins (source+target first, then target-only);
    otherwise ``default`` applies. Returns ``None`` when no network is
    configured (zero network delay).
    """
    if network is None:
        return None
    for edge in network.edges:
        if edge.source == source and edge.target == target:
            return NetworkLinkSpec(latency=edge.latency, jitter=edge.jitter)
    for edge in network.edges:
        if edge.target == target:
            return NetworkLinkSpec(latency=edge.latency, jitter=edge.jitter)
    return network.default


def network_delay(link: NetworkLinkSpec | None, rng: Generator) -> float:
    """Return the simulated one-way network delay (seconds) for a call.

    ``latency`` is the base delay; ``jitter`` is applied as a uniform
    ``[-jitter, +jitter]`` perturbation, floored at zero.
    """
    if link is None:
        return 0.0
    if link.jitter > 0:
        return max(0.0, link.latency + link.jitter * (2.0 * float(rng.uniform(0.0, 1.0)) - 1.0))
    return link.latency
