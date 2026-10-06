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


def _serialise(device: Device) -> dict:
    return {
        "id": device.id,
        "device_id": device.device_id,
        # Declared by the node in its handshake; never inferred.
        "kind": device.kind.value,
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
    return {"items": [_serialise(d) for d in device_service.list_devices(db)]}


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
def live_state(user: CurrentUser):
    """Which sessions currently have a processor and subscribers attached."""
    return registry.status()


@router.get("/{device_id}")
def get_device(device_id: str, user: CurrentUser, db: DbDep):
    device = db.execute(select(Device).where(Device.device_id == device_id)).scalar_one_or_none()
    if device is None:
        raise DeviceNotFound()
    return _serialise(device)
