"""In-memory registry of active SessionProcessors.

One processor per active session, shared by both leg sockets. This is where
ingestion, persistence and broadcast meet:

    packet -> processor -> events -> [persist] + [broadcast]

CPU-bound signal processing runs in a worker thread so the event loop stays
responsive to other sockets while a burst of samples is being filtered.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from app.core.logging import get_logger, log_event
from app.db.database import SessionLocal
from app.db.models.patient import Leg
from app.processing.analytics import Event, SessionProcessor
from app.realtime import live_events
from app.realtime.ws_manager import manager
from app.services import session_service

logger = get_logger("rehabsense.live")


@dataclass
class LiveSession:
    session_id: int
    processor: SessionProcessor
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    attached_legs: set[Leg] = field(default_factory=set)
    # Monotonic per-session event counter; see LiveRegistry._stamp.
    seq: int = 0


class LiveRegistry:
    def __init__(self) -> None:
        self._sessions: dict[int, LiveSession] = {}
        self._guard = asyncio.Lock()

    async def get_or_create(
        self, session_id: int, *, exercise_type: str, operated_leg: Leg | None,
        expected_reps: int | None = None,
    ) -> LiveSession:
        async with self._guard:
            live = self._sessions.get(session_id)
            if live is None:
                live = LiveSession(
                    session_id=session_id,
                    processor=SessionProcessor(
                        session_id, exercise_type, operated_leg,
                        started_at=0.0, expected_reps=expected_reps,
                    ),
                )
                self._sessions[session_id] = live
                log_event(logger, "live_session_opened", session_id=session_id,
                          exercise=exercise_type)
            return live

    def get(self, session_id: int) -> LiveSession | None:
        return self._sessions.get(session_id)

    async def close(self, session_id: int) -> None:
        async with self._guard:
            self._sessions.pop(session_id, None)
        manager.close_session(session_id)
        log_event(logger, "live_session_closed", session_id=session_id)

    # ----------------------------------------------------------------- #

    @staticmethod
    def _stamp(live: "LiveSession", events: list[Event]) -> None:
        """Number events in creation order, while the session lock is held.

        Ordering is decided here, not at delivery: `handle_events` awaits a
        database write before broadcasting, and that await lets two concurrent
        leg handlers interleave. Without a sequence a dashboard could apply an
        older connection snapshot last and show a streaming leg as
        disconnected until the next event arrived.
        """
        for event in events:
            live.seq += 1
            event.seq = live.seq

    async def handle_events(
        self, session_id: int, events: list[Event], *, stamped: bool = False
    ) -> None:
        """Broadcast then persist. Persistence failure must not stop the stream."""
        if not events:
            return
        if not stamped:
            live = self._sessions.get(session_id)
            if live is not None:
                self._stamp(live, events)

        # Broadcast first: delivery to an open dashboard should not wait on a
        # database round trip, and the queue puts below never await.
        for event in events:
            await manager.broadcast(session_id, live_events.from_processor_event(event))
        await asyncio.to_thread(self._persist, session_id, events)

    def _persist(self, session_id: int, events: list[Event]) -> None:
        db = SessionLocal()
        try:
            for event in events:
                if event.type == "metric_update":
                    session_service.persist_metric(db, session_id, event.payload)
                elif event.type == "rep_event":
                    session_service.persist_rep(db, session_id, event.payload)
                elif event.type == "risk_flag":
                    session_service.persist_risk(db, session_id, event.payload)
                elif event.type == "connection_status":
                    for leg_key, leg in (("left", Leg.LEFT), ("right", Leg.RIGHT)):
                        state = event.payload.get(leg_key)
                        if isinstance(state, dict):
                            session_service.update_device_link(db, session_id, leg, state)
            db.commit()
        except Exception:  # pragma: no cover - defensive
            db.rollback()
            logger.exception("failed to persist live events")
        finally:
            db.close()

    async def process_packet(
        self, session_id: int, leg: Leg, samples: list, seq: int | None
    ) -> None:
        live = self._sessions.get(session_id)
        if live is None:
            return
        async with live.lock:
            # Filtering and fusion are CPU-bound; keep them off the event loop.
            events = await asyncio.to_thread(live.processor.process, leg, samples, seq)
        await self.handle_events(session_id, events)

    async def attach(self, session_id: int, leg: Leg, hello) -> None:
        live = self._sessions.get(session_id)
        if live is None:
            return
        async with live.lock:
            events = live.processor.on_hello(leg, hello)
            live.attached_legs.add(leg)
            self._stamp(live, events)
        await self.handle_events(session_id, events, stamped=True)

    async def detach(self, session_id: int, leg: Leg) -> None:
        live = self._sessions.get(session_id)
        if live is None:
            return
        async with live.lock:
            events = live.processor.on_disconnect(leg)
            live.attached_legs.discard(leg)
            self._stamp(live, events)
        await self.handle_events(session_id, events, stamped=True)

    async def finalize(self, session_id: int, reported_pain: float | None = None) -> dict | None:
        live = self._sessions.get(session_id)
        if live is None:
            return None
        async with live.lock:
            summary = await asyncio.to_thread(live.processor.finalize, reported_pain)
        return summary

    def status(self) -> dict:
        return {
            "active_sessions": sorted(self._sessions),
            "count": len(self._sessions),
            "subscribers": {
                sid: manager.subscriber_count(sid) for sid in sorted(self._sessions)
            },
        }


registry = LiveRegistry()


@contextlib.asynccontextmanager
async def suppress_errors():  # pragma: no cover - convenience
    try:
        yield
    except Exception:
        logger.exception("live pipeline error")
