"""Device and sensor registration.

A device row is created the first time a node introduces itself, and its
declared capabilities become sensor rows. Whether a node is real hardware or
the simulator comes from what it declared — never from a guess.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.database import SessionLocal
from app.db.models.audit import AuditAction
from app.db.models.device import (
    Device,
    DeviceKind,
    DeviceStatus,
    Sensor,
    SensorLocation,
    SensorStatus,
    SensorType,
)
from app.db.models.patient import Leg
from app.db.models.session import SessionDeviceLink
from app.hardware.protocol import Capability, Hello
from app.services import audit_service

_CAPABILITY_MAP = {
    Capability.THIGH_IMU: (SensorType.IMU, SensorLocation.THIGH),
    Capability.SHIN_IMU: (SensorType.IMU, SensorLocation.SHIN),
    Capability.FSR: (SensorType.FSR, SensorLocation.FOOT),
}


def register_from_hello(session_id: int, leg: Leg, hello: Hello) -> int:
    """Upsert the device and its sensors; link it to the session's leg."""
    db: DbSession = SessionLocal()
    try:
        device = db.execute(
            select(Device).where(Device.device_id == hello.device_id)
        ).scalar_one_or_none()

        if device is None:
            device = Device(device_id=hello.device_id)
            db.add(device)

        # Protocol v1 nodes cannot authenticate, so a non-simulated v1 node is
        # UNVERIFIED -- never assumed to be physical hardware.
        device.kind = DeviceKind.SIMULATOR if hello.simulated else DeviceKind.UNVERIFIED
        device.leg = leg
        device.firmware_version = hello.firmware_version
        device.protocol_version = hello.protocol_version
        device.status = DeviceStatus.ONLINE
        device.last_seen = datetime.now(timezone.utc)
        device.sample_rate_hz = 100.0
        db.flush()

        declared = set(hello.sensors)
        existing = {s.capability: s for s in device.sensors}

        for capability in declared:
            sensor_type, location = _CAPABILITY_MAP[capability]
            sensor = existing.get(capability.value)
            if sensor is None:
                sensor = Sensor(
                    device_pk=device.id, type=sensor_type, location=location,
                    capability=capability.value,
                )
                db.add(sensor)
            sensor.status = SensorStatus.OK
            sensor.last_seen = datetime.now(timezone.utc)

        # A capability the node no longer declares is ABSENT, not deleted —
        # the history of what it once had stays visible.
        for capability_value, sensor in existing.items():
            if capability_value not in {c.value for c in declared}:
                sensor.status = SensorStatus.ABSENT

        link = db.execute(
            select(SessionDeviceLink).where(
                SessionDeviceLink.session_id == session_id, SessionDeviceLink.leg == leg
            )
        ).scalar_one_or_none()
        if link is None:
            link = SessionDeviceLink(session_id=session_id, leg=leg)
            db.add(link)
        link.device_id = device.id
        link.fsr_available = Capability.FSR in declared

        audit_service.record(
            db, action=AuditAction.DEVICE_CONNECTED, entity_type="device",
            entity_id=device.device_id, session_id=session_id, leg=leg.value,
            simulated=hello.simulated,
        )
        db.commit()
        return device.id
    finally:
        db.close()


def mark_offline(device_id: str) -> None:
    db: DbSession = SessionLocal()
    try:
        device = db.execute(
            select(Device).where(Device.device_id == device_id)
        ).scalar_one_or_none()
        if device:
            device.status = DeviceStatus.OFFLINE
            device.last_seen = datetime.now(timezone.utc)
            audit_service.record(
                db, action=AuditAction.DEVICE_DISCONNECTED, entity_type="device",
                entity_id=device_id,
            )
            db.commit()
    finally:
        db.close()


def list_devices(db: DbSession) -> list[Device]:
    return list(db.execute(select(Device).order_by(Device.last_seen.desc().nullslast())).scalars())
