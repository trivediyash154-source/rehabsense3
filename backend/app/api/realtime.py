"""WebSocket endpoints.

    /ws/ingest/{session_id}?leg=LEFT|RIGHT   -- devices and the simulator
    /ws/live/{session_id}                    -- dashboards

Both paths are exactly as documented. There is deliberately no separate route
for "real hardware": firmware and the simulator are indistinguishable to this
code apart from the `simulated` flag each declares in its handshake.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from pydantic import ValidationError

from app.core.logging import get_logger, log_event
from app.db.database import SessionLocal
from app.db.models.patient import Leg
from app.db.models.session import SessionStatus
from app.hardware.protocol import (
    PROTOCOL_VERSION,
    DataPacket,
    Hello,
    HelloAck,
    ProtocolError,
)
from app.realtime import live_events
from app.realtime.ws_manager import manager
from app.services import device_service
from app.services.live_registry import registry

# A node on a poor link may emit occasional rubbish; a node that emits nothing
# but rubbish is broken. Tolerate the former, disconnect the latter.
MAX_BAD_PACKETS = 50

router = APIRouter()
logger = get_logger("rehabsense.ingest")


def _load_session(session_id: int):
    """Read the session's static facts once, then release the DB session."""
    db = SessionLocal()
    try:
        from app.db.models.session import Session as SessionModel

        session = db.get(SessionModel, session_id)
        if session is None:
            return None
        return {
            "id": session.id,
            "exercise_type": session.exercise_type.value,
            "status": session.status,
            "operated_leg": session.patient.operated_leg if session.patient else None,
        }
    finally:
        db.close()


@router.websocket("/ws/ingest/{session_id}")
async def ingest(websocket: WebSocket, session_id: int, leg: str = Query(...)):
    await websocket.accept()

    try:
        leg_enum = Leg(leg.upper())
    except ValueError:
        await websocket.send_json(
            ProtocolError(code="INVALID_LEG", message="leg must be LEFT or RIGHT").model_dump()
        )
        await websocket.close(code=1008)
        return

    info = _load_session(session_id)
    if info is None:
        await websocket.send_json(
            ProtocolError(code="SESSION_NOT_FOUND", message=f"Session {session_id} not found").model_dump()
        )
        await websocket.close(code=1008)
        return
    if info["status"] is SessionStatus.COMPLETED:
        await websocket.send_json(
            ProtocolError(code="SESSION_ALREADY_COMPLETED",
                          message="This session has been completed.").model_dump()
        )
        await websocket.close(code=1008)
        return

    # ---- handshake ------------------------------------------------------ #
    try:
        raw = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        hello = Hello.model_validate(raw)
    except (asyncio.TimeoutError, ValidationError, ValueError) as exc:
        await websocket.send_json(
            ProtocolError(
                code="INVALID_HANDSHAKE",
                message=f"Expected a valid hello frame: {exc}",
            ).model_dump()
        )
        await websocket.close(code=1008)
        return
    except WebSocketDisconnect:
        return

    if hello.leg is not None and hello.leg.value != leg_enum.value:
        await websocket.send_json(
            ProtocolError(code="LEG_MISMATCH",
                          message="hello.leg does not match the query parameter").model_dump()
        )
        await websocket.close(code=1008)
        return

    live = await registry.get_or_create(
        session_id,
        exercise_type=info["exercise_type"],
        operated_leg=info["operated_leg"],
    )

    # Register the device and its declared sensors. Capability negotiation is
    # a record of what the node *claims*, never a requirement.
    await asyncio.to_thread(device_service.register_from_hello, session_id, leg_enum, hello)
    await registry.attach(session_id, leg_enum, hello)

    await websocket.send_json(
        HelloAck(
            session_id=session_id,
            server_time=time.time(),
            sample_rate_hz=100.0,
            accepted_capabilities=hello.sensors,
        ).model_dump(mode="json")
    )
    log_event(
        logger, "device_attached", session_id=session_id, leg=leg_enum.value,
        device_id=hello.device_id, simulated=hello.simulated,
        protocol=hello.protocol_version, capabilities=[c.value for c in hello.sensors],
    )

    # ---- data loop ------------------------------------------------------ #
    bad_packets = 0
    try:
        while True:
            # Received as text and parsed here rather than via receive_json():
            # a single corrupt frame -- a partial write from a node on a weak
            # link, say -- must be discarded like any other malformed packet,
            # not tear down a session that is otherwise streaming fine.
            text = await websocket.receive_text()
            try:
                raw = json.loads(text)
            except (ValueError, TypeError):
                bad_packets += 1
                log_event(logger, "invalid_packet", session_id=session_id,
                          leg=leg_enum.value, count=bad_packets, reason="not_json")
                await websocket.send_json(
                    ProtocolError(code="INVALID_SENSOR_PACKET",
                                  message="Packet was not valid JSON.").model_dump()
                )
                if bad_packets > MAX_BAD_PACKETS:
                    await websocket.close(code=1008)
                    return
                continue

            if not isinstance(raw, dict):
                bad_packets += 1
                await websocket.send_json(
                    ProtocolError(code="INVALID_SENSOR_PACKET",
                                  message="Packet must be a JSON object.").model_dump()
                )
                if bad_packets > MAX_BAD_PACKETS:
                    await websocket.close(code=1008)
                    return
                continue

            kind = raw.get("type")

            if kind == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
                continue
            if kind != "data":
                continue

            try:
                packet = DataPacket.model_validate(raw)
            except ValidationError as exc:
                # One malformed packet must never end the session.
                bad_packets += 1
                log_event(logger, "invalid_packet", session_id=session_id,
                          leg=leg_enum.value, count=bad_packets)
                await websocket.send_json(
                    ProtocolError(
                        code="INVALID_SENSOR_PACKET",
                        message=str(exc.errors()[0].get("msg", "malformed packet"))[:180],
                    ).model_dump()
                )
                if bad_packets > MAX_BAD_PACKETS:
                    await websocket.close(code=1008)
                    return
                continue

            await registry.process_packet(session_id, leg_enum, packet.samples, raw.get("seq"))

    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - defensive
        logger.exception("ingest loop failed")
    finally:
        # A dropped socket is normal: analytics pauses for this leg, the
        # session stays open, and reconnecting resumes it.
        await registry.detach(session_id, leg_enum)
        await asyncio.to_thread(device_service.mark_offline, hello.device_id)
        log_event(logger, "device_detached", session_id=session_id, leg=leg_enum.value,
                  device_id=hello.device_id)


def _ticket_holder(ticket: str | None, session_id: int) -> int | None:
    """Validate a live-socket ticket against this session id.

    Returns the user id, or None if the ticket is missing, expired, of the
    wrong kind, or was issued for a different session.
    """
    if not ticket:
        return None
    try:
        claims = decode_token(ticket, expected="ws")
    except Exception:
        return None
    if claims.get("sid") != session_id:
        return None
    return int(claims["sub"])


@router.websocket("/ws/live/{session_id}")
async def live(websocket: WebSocket, session_id: int, ticket: str | None = Query(default=None)):
    """Dashboard feed. Server -> client only.

    Requires a ticket from `POST /api/auth/ws-ticket`, which is only issued to
    a caller already permitted to read the session. Without this the socket
    would stream one patient's live movement data to anyone who guessed a
    session id.
    """
    await websocket.accept()

    viewer_id = _ticket_holder(ticket, session_id)
    if viewer_id is None:
        await websocket.send_json(
            {"type": "error", "code": "UNAUTHORIZED",
             "message": "A valid live-session ticket is required."}
        )
        await websocket.close(code=1008)
        return

    info = _load_session(session_id)
    if info is None:
        # Same response an unauthorised session gets, so the socket cannot be
        # used to discover which session ids exist.
        await websocket.send_json({"type": "error", "code": "SESSION_NOT_FOUND"})
        await websocket.close(code=1008)
        return

    sub = await manager.subscribe(session_id, websocket)
    await websocket.send_json(
        live_events.session_status(
            {"session_id": session_id, "status": info["status"].value,
             "exercise_type": info["exercise_type"]}
        )
    )

    # A live processor may already exist; replay its current state immediately.
    existing = registry.get(session_id)
    if existing is not None:
        await websocket.send_json(
            live_events.from_processor_event(existing.processor.connection_event())
        )

    pump = asyncio.create_task(manager.pump(sub))
    try:
        while True:
            # Dashboards send nothing; this detects a closed socket.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover
        pass
    finally:
        pump.cancel()
        await manager.unsubscribe(session_id, sub)
