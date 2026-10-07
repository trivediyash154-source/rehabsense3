"""Device inventory and per-session connection state."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from pydantic import BaseModel, Field

from app.core.exceptions import DeviceNotFound, Forbidden
from app.db.models.user import Role
from app.services import sensing_service
from app.db.models.device import Device
from app.services import device_service
from app.services.live_registry import registry
from app.db.models.base import utc_iso

router = APIRouter(prefix="/devices", tags=["devices"])


_KIND_PROVENANCE = {"HARDWARE": "PHYSICAL_REGISTERED", "UNVERIFIED": "PHYSICAL_UNVERIFIED",
                    "SIMULATOR": "SIMULATED"}


def _recording_provenance(db) -> dict[int, dict]:
    """Per device: the provenance of its most recent recording, and counts."""
    from sqlalchemy import func

    from app.db.models.sensing import Recording

    rows = db.execute(select(Recording.device_pk, Recording.provenance, func.count(Recording.id),
                             func.max(Recording.created_at))
                      .where(Recording.device_pk.is_not(None))
                      .group_by(Recording.device_pk, Recording.provenance)).all()
    out: dict[int, dict] = {}
    for device_pk, provenance, count, latest in rows:
        entry = out.setdefault(device_pk, {"counts": {}, "latest": None, "provenance": None})
        entry["counts"][provenance] = count
        if entry["latest"] is None or (latest and latest > entry["latest"]):
            entry["latest"], entry["provenance"] = latest, provenance
    return out


def _serialise(device: Device, recordings: dict | None = None) -> dict:
    rec = (recordings or {}).get(device.id) or {}
    return {
        "id": device.id,
        "device_id": device.device_id,
        # Declared by the node in its handshake; never inferred.
        "kind": device.kind.value,
        # Where its data comes from: the latest recording's provenance (set at
        # each handshake from authentication), else what its kind implies.
        "provenance": rec.get("provenance") or _KIND_PROVENANCE.get(device.kind.value),
        "recordings_by_provenance": rec.get("counts") or {},
        "simulated": device.kind.value == "SIMULATOR",
        # True only for a device registered by an admin/technician and
        # authenticated with its own key -- the only data counted as physical.
        "verified_hardware": bool(device.verified_hardware),
        "revoked": device.revoked_at is not None,
        "key_expires_at": utc_iso(device.key_expires_at),
        "registered_at": utc_iso(device.registered_at),
        "leg": device.leg.value if device.leg else None,
        "firmware_version": device.firmware_version,
        "protocol_version": device.protocol_version,
        "status": device.status.value,
        "last_seen": utc_iso(device.last_seen),
        "sample_rate_hz": device.sample_rate_hz,
        "battery_level": device.battery_level,
        "sensors": [
            {
                "type": s.type.value, "location": s.location.value,
                "capability": s.capability, "status": s.status.value,
                "last_seen": utc_iso(s.last_seen),
            }
            for s in device.sensors
        ],
    }


@router.get("")
def list_devices(user: CurrentUser, db: DbDep):
    recordings = _recording_provenance(db)
    return {"items": [_serialise(d, recordings) for d in device_service.list_devices(db)]}


class RegisterDevice(BaseModel):
    device_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    notes: str | None = Field(default=None, max_length=500)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


def _require_device_admin(user) -> None:
    if user.role not in (Role.ADMIN, Role.TECHNICIAN):
        raise Forbidden("Registering hardware requires an admin or technician account.")


@router.post("/register", status_code=201)
def register_device(payload: RegisterDevice, user: CurrentUser, db: DbDep):
    """Register a physical device and issue its key.

    The key is returned once and stored only as a SHA-256 hash. Put it in the
    firmware's config.h (DEVICE_KEY). Only streams authenticated with it are
    recorded as LIVE hardware; registering again rotates the key.
    """
    _require_device_admin(user)
    key = sensing_service.register_hardware(db, payload.device_id, user.id, payload.notes,
                                            payload.expires_in_days)
    db.commit()
    return {"device_id": payload.device_id, "device_key": key,
            "note": "Shown once. Store it in the device's config.h as DEVICE_KEY."}


@router.post("/{device_id}/revoke")
def revoke_device(device_id: str, user: CurrentUser, db: DbDep):
    _require_device_admin(user)
    if not sensing_service.revoke_hardware(db, device_id, user.id):
        raise DeviceNotFound()
    db.commit()
    return {"device_id": device_id, "verified_hardware": False}


@router.get("/live")
def live_state(user: CurrentUser, db: DbDep):
    """Which sessions currently have a processor and subscribers attached.

    `physical_online` answers "is a real, registered ESP32 streaming right
    now?" from the database, so any API instance gives the same answer: a
    registered (keyed) device that is ONLINE and was seen in the last minute.
    """
    from datetime import datetime, timedelta, timezone

    from app.db.models.base import as_utc
    from app.db.models.device import DeviceKind, DeviceStatus

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
    online = [d for d in db.execute(select(Device).where(
        Device.kind == DeviceKind.HARDWARE, Device.status == DeviceStatus.ONLINE,
        Device.verified_hardware.is_(True), Device.revoked_at.is_(None))).scalars()
        if d.last_seen is not None and as_utc(d.last_seen) >= cutoff]
    return {**registry.status(),
            "physical_online": [{"device_id": d.device_id, "last_seen": utc_iso(d.last_seen),
                                 "firmware_version": d.firmware_version,
                                 "sample_rate_hz": d.sample_rate_hz} for d in online],
            "checked_at": utc_iso(datetime.now(timezone.utc))}


@router.get("/{device_id}")
def get_device(device_id: str, user: CurrentUser, db: DbDep):
    device = db.execute(select(Device).where(Device.device_id == device_id)).scalar_one_or_none()
    if device is None:
        raise DeviceNotFound()
    return _serialise(device, _recording_provenance(db))
