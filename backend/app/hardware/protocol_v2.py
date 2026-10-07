"""Wire contract v2: one ESP32 carrying two MPU6050s and N force channels.

This is the RehabSense target hardware:

    1 x ESP32  ── I2C ──  MPU6050 (LEFT,  0x68)
                    └──   MPU6050 (RIGHT, 0x69)
               ── ADC1 ── force channel(s), e.g. FSR402 voltage dividers

v1 (`protocol.py`) assumed one node per leg with a thigh and a shin IMU each.
It stays in place, untouched, for the existing per-leg pipeline. v2 is a
separate socket (`/ws/ingest/v2/{session_id}`) and a separate processor, so
neither can silently reinterpret the other's packets.

Design rules carried over from v1:
  * versioned handshake, capability negotiation instead of hard failure
  * a malformed packet is rejected without ending the session
  * `simulated` is declared by the sender, never inferred

New in v2:
  * LEFT and RIGHT IMUs travel in the *same* sample with one device
    timestamp, because they are read by the same MCU in the same tick. That
    is what makes left/right timing comparisons meaningful at all.
  * Either IMU may be `null` in a sample (an I2C read failed). That is a
    reportable sensor dropout, not a malformed packet.
  * The number of force channels is declared, not assumed. Zero is valid.
  * Force values are whatever the firmware declares as `unit`. For an FSR402
    on a voltage divider that is a normalised ADC reading (0..1), which is a
    *monotonic load proxy*, not newtons. Nothing downstream calls it force in
    newtons unless a channel declares `unit: "N"` after a real calibration.
"""

from __future__ import annotations

import enum
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROTOCOL_VERSION_V2 = 2

# Sampling rates the backend will accept a declaration of. The MPU6050 can
# output up to 1 kHz; the ESP32 + Wi-Fi + JSON path is what limits us. These
# bounds reject typos (e.g. 10000) without hard-coding one rate.
MIN_RATE_HZ = 10.0
MAX_RATE_HZ = 400.0


class Side(str, enum.Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class Placement(str, enum.Enum):
    """Where an IMU is strapped. Declared by whoever fits the device."""

    SHANK = "SHANK"
    THIGH = "THIGH"
    FOOT = "FOOT"
    WRIST = "WRIST"
    FOREARM = "FOREARM"
    UPPER_ARM = "UPPER_ARM"
    OTHER = "OTHER"


class ForceUnit(str, enum.Enum):
    # Raw ADC counts divided by full scale: value = counts / 4095 on the
    # ESP32's 12-bit ADC1 (counts = round(value * 4095)). Monotonic in load,
    # non-linear, sensor- and temperature-dependent. NOT force.
    ADC_NORM = "adc_norm"
    # Only after calibration against a reference load cell; the channel must
    # then cite that calibration (`calibration_ref`).
    NEWTON = "N"


class ImuDescriptor(BaseModel):
    side: Side
    placement: Placement = Placement.SHANK
    model: str = Field(default="MPU6050", max_length=40)
    i2c_address: str | None = Field(default=None, max_length=8)
    accel_range_g: float | None = Field(default=None, gt=0, le=32)
    gyro_range_dps: float | None = Field(default=None, gt=0, le=4000)
    # Boot-time evidence reported by the firmware: the WHO_AM_I register
    # ("0x68" for a genuine MPU6050) and whether the range/filter
    # configuration read back correctly after it was written.
    who_am_i: str | None = Field(default=None, max_length=8)
    config_readback_ok: bool | None = None


class ForceChannelDescriptor(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    # None means "not associated with one limb" (e.g. a handle or a plate).
    side: Side | None = None
    location: str = Field(default="UNSPECIFIED", max_length=32)
    sensor: str = Field(default="FSR402", max_length=40)
    unit: ForceUnit = ForceUnit.ADC_NORM
    # Required for unit "N": identifier of the reference calibration (transfer
    # function, reference instrument, date) documented in docs/FORCE_CALIBRATION.md.
    calibration_ref: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _newtons_need_calibration(self) -> "ForceChannelDescriptor":
        if self.unit is ForceUnit.NEWTON and not self.calibration_ref:
            raise ValueError("a force channel may only report newtons with a calibration_ref")
        return self


class HelloV2(BaseModel):
    """First frame after the socket opens."""

    type: str = "hello"
    protocol_version: int
    device_id: str = Field(min_length=1, max_length=80)
    firmware_version: str = Field(default="unknown", max_length=40)
    # What the firmware is configured to sample at. The backend *measures* the
    # real rate from timestamps and reports any mismatch; it never trusts this
    # number alone.
    sample_rate_hz: float
    imus: list[ImuDescriptor] = Field(min_length=1, max_length=2)
    force_channels: list[ForceChannelDescriptor] = Field(default_factory=list, max_length=8)
    # Optional shared secret, required when the server sets DEVICE_INGEST_KEY.
    device_key: str | None = Field(default=None, max_length=200)
    # Simulator only. Real firmware omits it.
    simulated: bool = False
    scenario: str | None = Field(default=None, max_length=40)
    # Only meaningful with simulated=true: what kind of non-physical source.
    data_source: Literal["SIMULATOR", "PUBLIC_DATASET_REPLAY", "SYNTHETIC_DEMONSTRATION"] | None = None

    @field_validator("protocol_version")
    @classmethod
    def _supported(cls, v: int) -> int:
        if v != PROTOCOL_VERSION_V2:
            raise ValueError(
                f"unsupported protocol_version {v}; this endpoint speaks {PROTOCOL_VERSION_V2}"
            )
        return v

    @field_validator("sample_rate_hz")
    @classmethod
    def _rate(cls, v: float) -> float:
        if not (MIN_RATE_HZ <= v <= MAX_RATE_HZ):
            raise ValueError(f"sample_rate_hz must be within {MIN_RATE_HZ}-{MAX_RATE_HZ}")
        return v

    @model_validator(mode="after")
    def _unique(self) -> "HelloV2":
        sides = [imu.side for imu in self.imus]
        if len(sides) != len(set(sides)):
            raise ValueError("each IMU side may be declared once")
        ids = [c.id for c in self.force_channels]
        if len(ids) != len(set(ids)):
            raise ValueError("force channel ids must be unique")
        if self.data_source is not None and not self.simulated:
            raise ValueError("data_source may only be declared together with simulated=true")
        return self

    def imu(self, side: Side) -> ImuDescriptor | None:
        return next((i for i in self.imus if i.side is side), None)


def _finite(v: float) -> float:
    if not math.isfinite(v):
        raise ValueError("sensor values must be finite")
    return v


class ImuReading(BaseModel):
    """One MPU6050 reading. Accelerometer in g, gyroscope in deg/s."""

    model_config = ConfigDict(frozen=True)

    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float

    @field_validator("ax", "ay", "az", "gx", "gy", "gz")
    @classmethod
    def _check(cls, v: float) -> float:
        return _finite(v)


class DualSample(BaseModel):
    """One synchronous tick of the device: both IMUs and every force channel."""

    # Device-monotonic seconds (e.g. esp_timer_get_time() / 1e6). Not wall
    # clock: the backend estimates the offset and drift itself.
    ts: float
    # Per-sample counter, +1 every tick. Gaps are lost samples.
    seq: int = Field(ge=0)
    imu_left: ImuReading | None = None
    imu_right: ImuReading | None = None
    # Ordered exactly like HelloV2.force_channels. Missing channel -> null.
    force: list[float | None] = Field(default_factory=list, max_length=8)

    @field_validator("ts")
    @classmethod
    def _ts(cls, v: float) -> float:
        return _finite(v)

    @field_validator("force")
    @classmethod
    def _force(cls, v: list[float | None]) -> list[float | None]:
        return [None if x is None else _finite(x) for x in v]


class DataPacketV2(BaseModel):
    type: str = "data"
    samples: list[DualSample] = Field(min_length=1, max_length=500)
    # Device time when the packet left the radio. Optional; lets the backend
    # separate buffering delay on the device from network delay.
    sent_ts: float | None = None


class DeviceStatusV2(BaseModel):
    """Optional periodic health frame. Every field is optional."""

    type: str = "status"
    battery_v: float | None = Field(default=None, ge=0, le=10)
    battery_pct: float | None = Field(default=None, ge=0, le=100)
    wifi_rssi_dbm: float | None = Field(default=None, ge=-130, le=0)
    imu_left_ok: bool | None = None
    imu_right_ok: bool | None = None
    free_heap: int | None = Field(default=None, ge=0)
    uptime_s: float | None = Field(default=None, ge=0)
    # Firmware health counters (cumulative since boot). They let the server
    # tell "the device lost samples" apart from "the network lost packets".
    ring_overflows: int | None = Field(default=None, ge=0)
    i2c_errors_left: int | None = Field(default=None, ge=0)
    i2c_errors_right: int | None = Field(default=None, ge=0)
    imu_reinits_left: int | None = Field(default=None, ge=0)
    imu_reinits_right: int | None = Field(default=None, ge=0)
    sample_overruns: int | None = Field(default=None, ge=0)


class HelloAckV2(BaseModel):
    type: str = "hello_ack"
    protocol_version: int = PROTOCOL_VERSION_V2
    session_id: int
    server_time: float
    accepted_sample_rate_hz: float
    accepted_imus: list[Side]
    accepted_force_channels: list[str]
    # Calibration: a sensor health check, then a *detected* still period of
    # at least calibration_still_seconds, then slow repetitions. The server
    # announces each phase with a calibration_phase frame.
    calibration_health_seconds: float = 1.0
    calibration_still_seconds: float
    calibration_movement_seconds: float


class CalibrationPhaseV2(BaseModel):
    """Server -> device: the calibration phase changed (drives the LED)."""

    type: str = "calibration_phase"
    sequence: int
    phase: str   # HEALTH_CHECK | STILL | MOVEMENT | COMPLETE | FAILED
    instruction: str


def json_schemas() -> dict:
    """The canonical wire schema, generated from these models (single source)."""
    return {
        "protocol_version": PROTOCOL_VERSION_V2,
        "device_to_server": {
            "hello": HelloV2.model_json_schema(),
            "data": DataPacketV2.model_json_schema(),
            "status": DeviceStatusV2.model_json_schema(),
            "event": DeviceEventV2.model_json_schema(),
        },
        "server_to_device": {"hello_ack": HelloAckV2.model_json_schema(),
                             "calibration_phase": CalibrationPhaseV2.model_json_schema()},
    }


class DeviceEventV2(BaseModel):
    """Device -> server: an event stamped on the device clock (e.g. a button)."""

    type: str = "event"
    ts: float
    kind: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=120)

    @field_validator("ts")
    @classmethod
    def _ts(cls, v: float) -> float:
        return _finite(v)
