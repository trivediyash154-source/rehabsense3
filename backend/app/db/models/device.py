"""Devices and their sensors.

Two leg nodes, each an ESP32 with a thigh IMU, a shin IMU and an optional
foot-pressure sensor.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TimestampMixin
from app.db.models.patient import Leg

if TYPE_CHECKING:
    pass


class DeviceStatus(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class DeviceKind(str, enum.Enum):
    """Where a device's data comes from. Never guessed.

    HARDWARE is only ever assigned to a device registered by an administrator
    or technician that authenticated with its own key. A device that merely
    omits `simulated: true` proves nothing: test scripts do that too.
    """

    HARDWARE = "HARDWARE"        # registered, authenticated physical device
    SIMULATOR = "SIMULATOR"      # declared simulated: true
    UNVERIFIED = "UNVERIFIED"    # not simulated, but not authenticated either


class Device(Base, TimestampMixin):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    kind: Mapped[DeviceKind] = mapped_column(
        Enum(DeviceKind), default=DeviceKind.HARDWARE, nullable=False
    )
    leg: Mapped[Leg | None] = mapped_column(Enum(Leg))
    firmware_version: Mapped[str | None] = mapped_column(String(40))
    protocol_version: Mapped[int | None] = mapped_column()
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus), default=DeviceStatus.UNKNOWN, nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_rate_hz: Mapped[float | None] = mapped_column(Float)
    battery_level: Mapped[float | None] = mapped_column(Float)

    # Provenance. SHA-256 of the per-device key issued at registration (the
    # key itself is shown once and never stored).
    key_hash: Mapped[str | None] = mapped_column(String(64))
    verified_hardware: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    hardware_notes: Mapped[str | None] = mapped_column(String(500))
    # A revoked device is refused permanently (until re-registered).
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Optional key expiry; an expired key is refused.
    key_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sensors: Mapped[list["Sensor"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


class SensorType(str, enum.Enum):
    IMU = "IMU"
    FSR = "FSR"


class SensorLocation(str, enum.Enum):
    THIGH = "THIGH"
    SHIN = "SHIN"
    FOOT = "FOOT"


class SensorStatus(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    OK = "OK"
    DEGRADED = "DEGRADED"
    ABSENT = "ABSENT"


class Sensor(Base, TimestampMixin):
    __tablename__ = "sensors"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_pk: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[SensorType] = mapped_column(Enum(SensorType), nullable=False)
    location: Mapped[SensorLocation] = mapped_column(Enum(SensorLocation), nullable=False)
    # The capability string the node declared in its handshake.
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[SensorStatus] = mapped_column(
        Enum(SensorStatus), default=SensorStatus.UNKNOWN, nullable=False
    )
    calibration_state: Mapped[str | None] = mapped_column(String(24))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    device: Mapped["Device"] = relationship(back_populates="sensors")
