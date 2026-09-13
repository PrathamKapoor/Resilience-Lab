"""Event filtering, summarisation, and causal-timeline rendering.

These helpers operate on the canonical :class:`resiliencelab.events.Event`
stream produced by the runtime. They answer "what happened and why" without
requiring a database.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from resiliencelab.events import Event, EventType


def filter_events(
    events: Iterable[Event],
    *,
    event_type: EventType | str | None = None,
    service: str | None = None,
    request_id: int | None = None,
    source_service: str | None = None,
    target_service: str | None = None,
    start: float | None = None,
    end: float | None = None,
) -> list[Event]:
    """Return events matching the given filters (all optional)."""
    wanted_type = event_type.value if isinstance(event_type, EventType) else event_type
    result: list[Event] = []
    for event in events:
        if wanted_type is not None and event.event_type != wanted_type:
            continue
        if service is not None and event.service != service and event.target_service != service:
            continue
        if request_id is not None and event.request_id != request_id:
            continue
        if source_service is not None and event.source_service != source_service:
            continue
        if target_service is not None and event.target_service != target_service:
            continue
        if start is not None and event.elapsed < start:
            continue
        if end is not None and event.elapsed > end:
            continue
        result.append(event)
    return result


def event_summary(events: Iterable[Event]) -> dict[str, int]:
    """Count events by type."""
    return dict(Counter(event.event_type for event in events))


def causal_trace(events: Iterable[Event], *, limit: int = 200) -> str:
    """Render a chronological, human-readable causal event trace.

    Events are ordered by wall-clock ``elapsed`` (monotonic within a run)
    with ``sequence`` as a deterministic tie-break. This gives correct
    interleaving when experiment-lifecycle events and run events are combined.
    """
    ordered = sorted(events, key=lambda e: (e.elapsed, e.sequence))
    lines: list[str] = []
    for event in ordered[:limit]:
        bits: list[str] = [f"{event.elapsed:8.3f}", event.event_type]
        if event.request_id is not None:
            bits.append(f"req={event.request_id}")
        if event.attempt is not None:
            bits.append(f"attempt={event.attempt}")
        if event.target_service:
            bits.append(f"→ {event.target_service}")
        if event.reason:
            bits.append(f"({event.reason})")
        lines.append("  ".join(bits))
    if len(ordered) > limit:
        lines.append(f"  ... ({len(ordered) - limit} more events)")
    return "\n".join(lines)
