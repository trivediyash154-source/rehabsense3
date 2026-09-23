"""The wire contract between a leg node and the backend.

This is the single coupling point between hardware and software. Real ESP32
firmware and the simulator both speak exactly this — there is no second path
for "real hardware".

Design guarantees preserved from the specification:
  * versioned handshake
  * capability negotiation, not hard failure (a missing FSR is normal)
  * every field beyond accel + gyro is optional at the wire level
  * a malformed packet is rejected without killing the session
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTOCOL_VERSION = 1


class Leg(str, enum.Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class Capability(str, enum.Enum):
    THIGH_IMU = "thigh_imu"
    SHIN_IMU = "shin_imu"
    FSR = "fsr"


class SegmentSample(BaseModel):
    """One IMU reading. Accelerometer in g, gyroscope in deg/s."""

    model_config = ConfigDict(frozen=True)

    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float

    @field_validator("ax", "ay", "az", "gx", "gy", "gz")
    @classmethod
    def _finite(cls, v: float) -> float:
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("sensor values must be finite")
        return v


class Sample(BaseModel):
    """One time-stamped sample carrying both segments of a leg."""

    ts: float
    seq: int | None = None
    thigh: SegmentSample
    shin: SegmentSample
    # Optional by contract. Omitted entirely (not null) when unavailable.
    fsr: float | None = Field(default=None, ge=0.0, le=1.0)


class Hello(BaseModel):
    """Sent once, immediately after the socket opens."""

    type: str = "hello"
    protocol_version: int
    device_id: str = Field(min_length=1, max_length=80)
    leg: Leg
    firmware_version: str = Field(default="unknown", max_length=40)
    sensors: list[Capability] = Field(default_factory=list)
    # Optional, simulator-only. A real node omits it; the backend never
    # infers "simulated" from anything else.
    simulated: bool = False
    scenario: str | None = Field(default=None, max_length=40)

    @field_validator("protocol_version")
    @classmethod
    def _supported(cls, v: int) -> int:
        if v != PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol_version {v}; server speaks {PROTOCOL_VERSION}")
        return v

    def has(self, capability: Capability) -> bool:
        return capability in self.sensors


class HelloAck(BaseModel):
    type: str = "hello_ack"
    session_id: int
    server_time: float
    sample_rate_hz: float
    # Echoed back so the node knows what the server understood it to have.
    accepted_capabilities: list[Capability] = Field(default_factory=list)
    calibration_seconds: float = 2.5


class DataPacket(BaseModel):
    type: str = "data"
    leg: Leg
    samples: list[Sample] = Field(min_length=1, max_length=500)


class ProtocolError(BaseModel):
    type: str = "error"
    code: str
    message: str
