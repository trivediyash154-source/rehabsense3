"""WebSocket endpoints.

    /ws/ingest/{session_id}?leg=LEFT|RIGHT   -- devices and the simulator
    /ws/live/{session_id}                    -- dashboards

Both paths are exactly as documented. There is deliberately no separate route
for "real hardware": firmware and the simulator are indistinguishable to this
code apart from the `simulated` flag each declares in its handshake.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from pydantic import ValidationError

from app.core.config import get_settings
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

    from app.services.hw_registry import hw_registry

    if hw_registry.get(session_id) is not None:
        await websocket.send_json(
            ProtocolError(code="SESSION_PROTOCOL_CONFLICT",
                          message="This session is already receiving a protocol v2 stream.").model_dump()
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

    # Who may stream. Protocol v1 has no per-device keys, so without a fleet
    # key anyone who can reach this socket could push data into any active
    # session. Production (registered devices required) therefore accepts v1
    # only with DEVICE_INGEST_KEY, which the server's own simulator presents.
    settings = get_settings()
    refusal = None
    if hello.simulated and not settings.allow_simulated_devices:
        refusal = ("SIMULATED_DEVICES_DISABLED", "Simulated devices are disabled on this server.")
    elif settings.device_ingest_key:
        if not hmac.compare_digest((hello.device_key or "").encode(),
                                   settings.device_ingest_key.encode()):
            refusal = ("DEVICE_UNAUTHORIZED", "Device key missing or invalid.")
    elif settings.require_registered_devices:
        refusal = ("DEVICE_NOT_REGISTERED",
                   "Protocol v1 streams are not accepted here without a device key.")
    if refusal is not None:
        await websocket.send_json(ProtocolError(code=refusal[0], message=refusal[1]).model_dump())
        await websocket.close(code=1008)
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


# ---------------------------------------------------------------------- #
# Hardware v2: one ESP32, LEFT + RIGHT MPU6050, N force channels
# ---------------------------------------------------------------------- #

async def _refuse(websocket: WebSocket, code: str, message: str) -> None:
    await websocket.send_json(ProtocolError(code=code, message=message).model_dump())
    await websocket.close(code=1008)


@router.websocket("/ws/ingest/v2/{session_id}")
async def ingest_v2(websocket: WebSocket, session_id: int):
    """Dual-IMU device ingestion. See docs/SENSOR_PROTOCOL_V2.md."""
    import hmac

    from app.core.config import get_settings
    from app.hardware.protocol_v2 import (
        DataPacketV2,
        DeviceStatusV2,
        HelloAckV2,
        HelloV2,
    )
    from app.services import sensing_service
    from app.services.hw_registry import hw_registry

    settings = get_settings()
    await websocket.accept()

    info = _load_session(session_id)
    if info is None:
        await _refuse(websocket, "SESSION_NOT_FOUND", f"Session {session_id} not found")
        return
    if info["status"] is not SessionStatus.ACTIVE:
        await _refuse(websocket, "SESSION_NOT_ACTIVE", "This session is not active.")
        return
    if registry.get(session_id) is not None:
        # A v1 per-leg stream already feeds this session; mixing protocols
        # would merge two incompatible sensor layouts into one record.
        await _refuse(websocket, "SESSION_PROTOCOL_CONFLICT",
                      "This session is already receiving a protocol v1 stream.")
        return

    try:
        raw = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        hello = HelloV2.model_validate(raw)
    except (asyncio.TimeoutError, ValidationError, ValueError) as exc:
        await _refuse(websocket, "INVALID_HANDSHAKE", f"Expected a valid v2 hello frame: {exc}"[:300])
        return
    except WebSocketDisconnect:
        return

    if hello.simulated and not settings.allow_simulated_devices:
        await _refuse(websocket, "SIMULATION_DISABLED",
                      "This server does not accept simulated devices.")
        return

    existing = hw_registry.get(session_id)
    if existing is not None and existing.attached:
        await _refuse(websocket, "DEVICE_ALREADY_ATTACHED",
                      "A device is already streaming into this session.")
        return
    if existing is not None and existing.processor.hello.device_id != hello.device_id:
        await _refuse(websocket, "DEVICE_MISMATCH",
                      "A different device recorded the start of this session.")
        return

    def _provenance():
        db = SessionLocal()
        try:
            return sensing_service.resolve_provenance(db, hello)
        finally:
            db.close()

    provenance, refusal = await asyncio.to_thread(_provenance)
    # The fleet-wide key (if set) gates devices that have no key of their own;
    # a registered device has already been checked against its own key.
    if refusal is None and provenance != "PHYSICAL_REGISTERED" and settings.device_ingest_key:
        if not hmac.compare_digest((hello.device_key or "").encode(),
                                   settings.device_ingest_key.encode()):
            refusal = "DEVICE_UNAUTHORIZED"
    if refusal:
        await _refuse(websocket, refusal, {
            "DEVICE_UNAUTHORIZED": "Device key missing or invalid.",
            "DEVICE_REVOKED": "This device has been revoked.",
            "DEVICE_KEY_EXPIRED": "This device's key has expired; re-register it.",
            "DEVICE_NOT_REGISTERED": "Only registered devices may stream to this server.",
        }.get(refusal, "A registered hardware device cannot declare itself simulated."))
        return

    def _register():
        db = SessionLocal()
        try:
            device_pk = sensing_service.register_v2_device(db, session_id, hello, provenance)
            baseline = sensing_service.baseline_rom_for_session(db, session_id)
            return device_pk, baseline
        finally:
            db.close()

    device_pk, baseline = await asyncio.to_thread(_register)
    hw = await hw_registry.open(session_id, info["exercise_type"], hello, device_pk, baseline,
                                provenance)
    await hw_registry.attach(session_id, hello)

    await websocket.send_json(HelloAckV2(
        calibration_health_seconds=hw.processor.calibrator.health_seconds,
        session_id=session_id,
        server_time=time.time(),
        accepted_sample_rate_hz=hello.sample_rate_hz,
        accepted_imus=[i.side for i in hello.imus],
        accepted_force_channels=[c.id for c in hello.force_channels],
        calibration_still_seconds=hw.processor.calibrator.still_seconds,
        calibration_movement_seconds=hw.processor.calibrator.movement_seconds,
    ).model_dump(mode="json"))
    log_event(logger, "hw_device_attached", session_id=session_id, device_id=hello.device_id,
              simulated=hello.simulated, provenance=provenance, imus=[i.side.value for i in hello.imus],
              force_channels=len(hello.force_channels), rate=hello.sample_rate_hz)

    bad = 0
    last_phase = None
    try:
        while True:
            text = await websocket.receive_text()
            arrival = time.time()
            try:
                raw = json.loads(text)
                if not isinstance(raw, dict):
                    raise ValueError("not an object")
            except (ValueError, TypeError):
                bad += 1
                await websocket.send_json(ProtocolError(
                    code="INVALID_SENSOR_PACKET", message="Packet was not a JSON object.").model_dump())
                if bad > MAX_BAD_PACKETS:
                    await websocket.close(code=1008)
                    return
                continue
            kind = raw.get("type")
            if kind == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
                continue
            if kind == "event":
                from app.hardware.protocol_v2 import DeviceEventV2

                try:
                    await hw_registry.device_event(session_id, DeviceEventV2.model_validate(raw))
                except ValidationError:
                    pass
                continue
            if kind == "status":
                try:
                    status = DeviceStatusV2.model_validate(raw)
                except ValidationError:
                    continue
                await hw_registry.status(session_id, status.model_dump())
                continue
            if kind != "data":
                continue
            try:
                packet = DataPacketV2.model_validate(raw)
            except ValidationError as exc:
                bad += 1
                log_event(logger, "invalid_packet", session_id=session_id, count=bad, protocol=2)
                await websocket.send_json(ProtocolError(
                    code="INVALID_SENSOR_PACKET",
                    message=str(exc.errors()[0].get("msg", "malformed packet"))[:180],
                ).model_dump())
                if bad > MAX_BAD_PACKETS:
                    await websocket.close(code=1008)
                    return
                continue
            alive = await hw_registry.process(session_id, packet.samples, arrival, packet.sent_ts)
            phase = hw_registry.calibration_phase(session_id)
            if alive and phase != last_phase:
                last_phase = phase
                ev = hw_registry.get(session_id).processor.calibration_event().payload
                await websocket.send_json({"type": "calibration_phase", "sequence": ev["sequence"],
                                           "phase": phase, "instruction": ev["instruction"]})
            if not alive:
                # The session was ended from the UI; stop the device streaming
                # into nothing.
                await websocket.send_json(ProtocolError(
                    code="SESSION_ENDED", message="This session has ended.").model_dump())
                await websocket.close(code=1000)
                return
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - defensive
        logger.exception("v2 ingest loop failed")
    finally:
        await hw_registry.detach(session_id)

        def _offline():
            db = SessionLocal()
            try:
                sensing_service.mark_device_offline(db, hello.device_id)
            finally:
                db.close()
        await asyncio.to_thread(_offline)
        log_event(logger, "hw_device_detached", session_id=session_id, device_id=hello.device_id)


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
    from app.services.hw_registry import hw_registry

    hw = hw_registry.get(session_id)
    if hw is not None:
        # seq 0: a snapshot, never newer than the next stamped event.
        await websocket.send_json(live_events.from_processor_event(hw.processor.connection_event()))
        await websocket.send_json(live_events.from_processor_event(hw.processor.calibration_event()))

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
