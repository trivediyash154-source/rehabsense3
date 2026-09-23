"""Live events must reach a dashboard in the order they were created.

`handle_events` awaits a database write, and two leg handlers run
concurrently, so without an explicit sequence a dashboard can apply an older
connection snapshot last -- showing a leg that is actively streaming as
disconnected until the next event happens to arrive.
"""

from __future__ import annotations

import asyncio

from app.processing.analytics import Event
from app.services.live_registry import LiveRegistry


def test_events_are_numbered_in_creation_order() -> None:
    asyncio.run(_events_in_creation_order())


async def _events_in_creation_order() -> None:
    registry = LiveRegistry()
    live = await registry.get_or_create(9001, exercise_type="WALK", operated_leg=None)

    first = [Event("connection_status", {"n": 1})]
    second = [Event("connection_status", {"n": 2})]
    registry._stamp(live, first)
    registry._stamp(live, second)

    assert first[0].seq == 1
    assert second[0].seq == 2
    assert first[0].seq < second[0].seq


def test_sequence_is_per_session_and_monotonic() -> None:
    asyncio.run(_sequence_per_session())


async def _sequence_per_session() -> None:
    registry = LiveRegistry()
    a = await registry.get_or_create(9002, exercise_type="WALK", operated_leg=None)
    b = await registry.get_or_create(9003, exercise_type="WALK", operated_leg=None)

    for _ in range(5):
        events = [Event("metric_update", {})]
        registry._stamp(a, events)
    a_last = a.seq

    events_b = [Event("metric_update", {})]
    registry._stamp(b, events_b)

    assert a_last == 5
    # A second session starts its own numbering rather than sharing a counter.
    assert events_b[0].seq == 1


def test_the_wire_message_carries_the_sequence() -> None:
    from app.realtime import live_events

    event = Event("connection_status", {"left": {}, "right": {}})
    event.seq = 7
    message = live_events.from_processor_event(event)
    assert message["seq"] == 7
    assert message["type"] == "connection_status"


def test_an_unstamped_event_still_serialises() -> None:
    """Defensive: a seq of 0 means "unknown", which clients treat as always-apply."""
    from app.realtime import live_events

    message = live_events.from_processor_event(Event("metric_update", {}))
    assert message["seq"] == 0
