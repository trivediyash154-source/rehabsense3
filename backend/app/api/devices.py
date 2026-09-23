"""Device inventory and per-session connection state."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from app.core.exceptions import DeviceNotFound
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
