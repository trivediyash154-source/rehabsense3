"""Cross-instance relay for live dashboard messages over PostgreSQL LISTEN/NOTIFY.

Why: on a host that runs several instances of the API (Vercel Fluid compute,
any autoscaled container service), the instance processing a device's stream
is not necessarily the one holding a dashboard's WebSocket, and live state
lives in process memory. Every live message is therefore also published with
pg_notify; each instance that has a dashboard attached LISTENs and hands
messages from *other* instances to its local subscribers. No extra service is
needed: the relay rides on the PostgreSQL the API already uses.

Enabled with LIVE_RELAY=postgres (off by default: one process needs no relay).
Best effort, like any live view: a message larger than PostgreSQL's 8000-byte
NOTIFY limit is skipped and logged, and a dropped connection reconnects.
Recorded data never travels this way; it is persisted separately.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable

import psycopg

from app.core.config import get_settings
from app.core.logging import get_logger, log_event

logger = get_logger("rehabsense.relay")

CHANNEL = "rehabsense_live"
# PostgreSQL rejects NOTIFY payloads of 8000 bytes or more.
MAX_PAYLOAD_BYTES = 7900
INSTANCE_ID = uuid.uuid4().hex[:12]

Deliver = Callable[[int, dict], Awaitable[None]]


def _conninfo() -> str:
    # SQLAlchemy URL -> libpq/psycopg conninfo. Needs a direct (session-mode)
    # connection: LISTEN does not survive a transaction-mode pooler.
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def relay_enabled() -> bool:
    s = get_settings()
    return s.live_relay.strip().lower() == "postgres" and s.database_url.startswith("postgresql")


class PgRelay:
    def __init__(self, deliver: Deliver) -> None:
        self._deliver = deliver
        self._out: asyncio.Queue[str] | None = None
        self._publisher: asyncio.Task | None = None
        self._listener: asyncio.Task | None = None
        self.published = 0
        self.relayed_in = 0
        self.skipped_large = 0

    # --- outgoing ---------------------------------------------------------
    def publish(self, session_id: int, message: dict) -> None:
        """Queue one message for other instances. Never blocks the caller."""
        if not relay_enabled():
            return
        payload = json.dumps({"i": INSTANCE_ID, "s": session_id, "m": message},
                             separators=(",", ":"), default=str)
        if len(payload.encode()) > MAX_PAYLOAD_BYTES:
            self.skipped_large += 1
            log_event(logger, "relay_message_too_large", session_id=session_id,
                      type=message.get("type"), bytes=len(payload.encode()))
            return
        if self._publisher is None or self._publisher.done():
            self._out = asyncio.Queue(maxsize=2000)
            self._publisher = asyncio.create_task(self._publish_loop())
        assert self._out is not None
        try:
            self._out.put_nowait(payload)
        except asyncio.QueueFull:
            log_event(logger, "relay_queue_full", session_id=session_id)

    async def _publish_loop(self) -> None:
        assert self._out is not None
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(_conninfo(), autocommit=True) as conn:
                    while True:
                        payload = await self._out.get()
                        await conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, payload))
                        self.published += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # reconnect; the live view is best effort
                log_event(logger, "relay_publish_error", error=type(exc).__name__)
                await asyncio.sleep(1.0)

    # --- incoming ---------------------------------------------------------
    def ensure_listening(self) -> None:
        """Start listening once a dashboard is attached to this instance."""
        if not relay_enabled():
            return
        if self._listener is None or self._listener.done():
            self._listener = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(_conninfo(), autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    log_event(logger, "relay_listening", instance=INSTANCE_ID)
                    async for note in conn.notifies():
                        try:
                            data = json.loads(note.payload)
                        except ValueError:
                            continue
                        if data.get("i") == INSTANCE_ID:
                            continue  # already delivered locally
                        self.relayed_in += 1
                        with contextlib.suppress(Exception):
                            await self._deliver(int(data["s"]), data["m"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_event(logger, "relay_listen_error", error=type(exc).__name__)
                await asyncio.sleep(1.0)

    def stats(self) -> dict:
        return {"enabled": relay_enabled(), "instance": INSTANCE_ID, "published": self.published,
                "relayed_in": self.relayed_in, "skipped_large": self.skipped_large}
