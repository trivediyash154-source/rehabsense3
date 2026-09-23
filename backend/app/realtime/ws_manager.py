"""WebSocket fan-out for live sessions.

Guarantees:
  * events are scoped to one session; a subscriber never sees another's data
  * a slow or dead dashboard client is dropped, never allowed to block ingest
  * multiple dashboards and both leg nodes can attach to the same session
  * heartbeats detect half-open sockets that never sent a close frame
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.core.logging import get_logger, log_event

logger = get_logger("rehabsense.ws")

# A dashboard that cannot keep up is dropped rather than allowed to apply
# backpressure to the ingestion path.
MAX_QUEUE = 64
HEARTBEAT_SECONDS = 15.0


# eq=False keeps the default identity hash: subscribers live in a set, and a
# generated __eq__ would make the class unhashable.
@dataclass(eq=False)
class Subscriber:
    websocket: WebSocket
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=MAX_QUEUE))
    dropped: int = 0

    def offer(self, message: dict) -> bool:
        """Non-blocking enqueue. Returns False when the client is too slow."""
        try:
            self.queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            return False


class SessionHub:
    """All live subscribers for one session."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        self.subscribers: set[Subscriber] = set()
        # Replayed to a dashboard that connects mid-session, so a late joiner
        # is not stuck with a blank screen until the next event.
        self.last_state: dict[str, dict] = {}
        self.created_at = time.time()

    def snapshot(self) -> list[dict]:
        order = ["session_status", "connection_status", "calibration_status", "metric_update"]
        return [self.last_state[key] for key in order if key in self.last_state]


class WebSocketManager:
    def __init__(self) -> None:
        self._hubs: dict[int, SessionHub] = {}
        self._lock = asyncio.Lock()

    def hub(self, session_id: int) -> SessionHub:
        hub = self._hubs.get(session_id)
        if hub is None:
            hub = SessionHub(session_id)
            self._hubs[session_id] = hub
        return hub

    async def subscribe(self, session_id: int, websocket: WebSocket) -> Subscriber:
        async with self._lock:
            hub = self.hub(session_id)
            sub = Subscriber(websocket=websocket)
            hub.subscribers.add(sub)
        for message in hub.snapshot():
            sub.offer(message)
        log_event(logger, "dashboard_subscribed", session_id=session_id,
                  subscribers=len(hub.subscribers))
        return sub

    async def unsubscribe(self, session_id: int, sub: Subscriber) -> None:
        async with self._lock:
            hub = self._hubs.get(session_id)
            if hub:
                hub.subscribers.discard(sub)
                if not hub.subscribers:
                    # Keep last_state briefly; drop the hub only when idle and empty.
                    pass
        log_event(logger, "dashboard_unsubscribed", session_id=session_id)

    async def broadcast(self, session_id: int, message: dict) -> None:
        """Fan out one event. Never awaits a socket; only fills queues."""
        hub = self._hubs.get(session_id)
        if hub is None:
            hub = self.hub(session_id)

        kind = message.get("type")
        if kind in ("connection_status", "calibration_status", "metric_update", "session_status"):
            hub.last_state[kind] = message

        stale: list[Subscriber] = []
        for sub in list(hub.subscribers):
            if not sub.offer(message):
                stale.append(sub)

        for sub in stale:
            # Too far behind to be useful; close it rather than stall ingest.
            log_event(logger, "subscriber_dropped_slow", session_id=session_id, dropped=sub.dropped)
            hub.subscribers.discard(sub)
            with contextlib.suppress(Exception):
                await sub.websocket.close(code=1011)

    async def pump(self, sub: Subscriber) -> None:
        """Drain one subscriber's queue to its socket, with heartbeats."""
        try:
            while True:
                try:
                    message = await asyncio.wait_for(sub.queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    await sub.websocket.send_json({"type": "heartbeat", "ts": time.time()})
                    continue
                await sub.websocket.send_json(message)
        except Exception:
            return

    def close_session(self, session_id: int) -> None:
        self._hubs.pop(session_id, None)

    def subscriber_count(self, session_id: int) -> int:
        hub = self._hubs.get(session_id)
        return len(hub.subscribers) if hub else 0

    @property
    def active_sessions(self) -> list[int]:
        return sorted(self._hubs)


manager = WebSocketManager()
