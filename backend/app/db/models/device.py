"""Devices and their sensors.

Two leg nodes, each an ESP32 with a thigh IMU, a shin IMU and an optional
foot-pressure sensor.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
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
    """Distinguishes a real node from the simulator. Never guessed."""

    HARDWARE = "HARDWARE"
    SIMULATOR = "SIMULATOR"


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
