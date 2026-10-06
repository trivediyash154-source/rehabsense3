"""Sessions and the per-session records the analytics engine produces.

Raw 100 Hz samples are deliberately not persisted — only chart-ready
snapshots and discrete events, per the documented data model.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TimestampMixin
from app.db.models.patient import Leg

if TYPE_CHECKING:
    from app.db.models.device import Device
    from app.db.models.focus import FocusSession
    from app.db.models.patient import PatientProfile


class ExerciseType(str, enum.Enum):
    WALK = "WALK"
    SQUAT = "SQUAT"
    SIT_TO_STAND = "SIT_TO_STAND"
    STEP_UP = "STEP_UP"
    SINGLE_LEG_BALANCE = "SINGLE_LEG_BALANCE"
    KNEE_EXTENSION = "KNEE_EXTENSION"


class SessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SessionMode(str, enum.Enum):
    """Where the sensor stream came from. Never inferred — always recorded."""

    LIVE = "LIVE"               # a registered device authenticated with its own key
    SIMULATED = "SIMULATED"     # the sender declared simulated: true
    UNVERIFIED = "UNVERIFIED"   # not declared simulated, but not authenticated
    UNKNOWN = "UNKNOWN"         # nothing has connected yet


class RecordingMode(str, enum.Enum):
    STANDARD = "STANDARD"   # therapy session: analysis is the product
    RESEARCH = "RESEARCH"   # raw-data collection: raw samples are the product


class CalibrationState(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    exercise_type: Mapped[ExerciseType] = mapped_column(Enum(ExerciseType), nullable=False)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus), default=SessionStatus.ACTIVE, nullable=False, index=True
    )
    mode: Mapped[SessionMode] = mapped_column(
        Enum(SessionMode), default=SessionMode.UNKNOWN, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_pain: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    calibration_state: Mapped[CalibrationState] = mapped_column(
        Enum(CalibrationState), default=CalibrationState.PENDING, nullable=False
    )
    calibration_quality: Mapped[float | None] = mapped_column(Float)

    # Finalised summary, written once on end. Every downstream surface
    # (dashboard, receipt, report, comparison) reads these same numbers.
    summary: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[dict | None] = mapped_column(JSON)
    data_quality: Mapped[dict | None] = mapped_column(JSON)

    # Which formula version produced the numbers above.
    analytics_version: Mapped[str | None] = mapped_column(String(32))

    # 1 = per-leg nodes (thigh+shin IMUs each); 2 = one ESP32 with a LEFT and
    # a RIGHT MPU6050 plus force channels. Null until a device connects.
    protocol_version: Mapped[int | None] = mapped_column()

    # SIMULATED / PUBLIC_DATASET_REPLAY / PHYSICAL_UNVERIFIED /
    # PHYSICAL_REGISTERED (app/sensing/provenance.py). Set at the handshake.
    provenance: Mapped[str | None] = mapped_column(String(24))

    recording_mode: Mapped[RecordingMode] = mapped_column(
        Enum(RecordingMode), default=RecordingMode.STANDARD,
        server_default=RecordingMode.STANDARD.value, nullable=False)
    # Research recordings: protocol id/version, subject code, conditions.
    research_protocol: Mapped[dict | None] = mapped_column(JSON)

    # Idempotency key so a retried "start session" cannot create a duplicate.
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)

    # The Recovery Focus block this session was recorded inside, when the
    # patient started it from a planned block. Optional: a session started
    # from the live lab has no plan attached, and that is a real state.
    focus_id: Mapped[int | None] = mapped_column(
        ForeignKey("focus_sessions.id", ondelete="SET NULL"), index=True
    )

    patient: Mapped["PatientProfile"] = relationship(back_populates="sessions")
    metrics: Mapped[list["MetricSnapshot"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="MetricSnapshot.ts"
    )
    reps: Mapped[list["RepEvent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="RepEvent.ts"
    )
    risk_flags: Mapped[list["RiskFlag"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="RiskFlag.ts"
    )
    device_links: Mapped[list["SessionDeviceLink"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    focus: Mapped["FocusSession | None"] = relationship(back_populates="sessions")

    @property
    def duration_seconds(self) -> float | None:
        if not self.ended_at:
            return None
        return (self.ended_at - self.started_at).total_seconds()


class MetricSnapshot(Base):
    """One chart-ready row, written roughly once per second of session time."""

    __tablename__ = "metric_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Seconds since session start — what the replay/time-machine interpolate over.
    t_offset: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    left_knee_angle_deg: Mapped[float | None] = mapped_column(Float)
    right_knee_angle_deg: Mapped[float | None] = mapped_column(Float)
    rom_running_deg: Mapped[float | None] = mapped_column(Float)
    cadence_spm: Mapped[float | None] = mapped_column(Float)
    symmetry_index_pct: Mapped[float | None] = mapped_column(Float)
    recovery_score: Mapped[float | None] = mapped_column(Float)
    recovery_confidence: Mapped[float | None] = mapped_column(Float)
    score_contributions: Mapped[dict | None] = mapped_column(JSON)

    session: Mapped["Session"] = relationship(back_populates="metrics")


class RepEvent(Base):
    __tablename__ = "rep_events"
    __table_args__ = (UniqueConstraint("session_id", "leg", "rep_index", name="uq_rep_per_leg"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    t_offset: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    leg: Mapped[Leg] = mapped_column(Enum(Leg), nullable=False)
    rep_index: Mapped[int] = mapped_column(nullable=False)
    rom_deg: Mapped[float] = mapped_column(Float, nullable=False)
    peak_angle_deg: Mapped[float | None] = mapped_column(Float)
    min_angle_deg: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    smoothness: Mapped[float | None] = mapped_column(Float)
    quality_score: Mapped[float | None] = mapped_column(Float)

    session: Mapped["Session"] = relationship(back_populates="reps")


class RiskSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RiskFlag(Base):
    __tablename__ = "risk_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    t_offset: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    severity: Mapped[RiskSeverity] = mapped_column(Enum(RiskSeverity), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    source_metric: Mapped[str | None] = mapped_column(String(64))

    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped["Session"] = relationship(back_populates="risk_flags")


class ConnectionState(str, enum.Enum):
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"


class SessionDeviceLink(Base, TimestampMixin):
    """Per-session, per-leg connection and stream-health record."""

    __tablename__ = "session_device_links"
    __table_args__ = (UniqueConstraint("session_id", "leg", name="uq_session_leg"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    leg: Mapped[Leg] = mapped_column(Enum(Leg), nullable=False)
    state: Mapped[ConnectionState] = mapped_column(
        Enum(ConnectionState), default=ConnectionState.DISCONNECTED, nullable=False
    )
    first_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    packets_received: Mapped[int] = mapped_column(default=0, nullable=False)
    packets_dropped: Mapped[int] = mapped_column(default=0, nullable=False)
    sequence_gaps: Mapped[int] = mapped_column(default=0, nullable=False)
    connected_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fsr_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    calibration_state: Mapped[CalibrationState] = mapped_column(
        Enum(CalibrationState), default=CalibrationState.PENDING, nullable=False
    )
    signal_quality: Mapped[float | None] = mapped_column(Float)

    session: Mapped["Session"] = relationship(back_populates="device_links")
    device: Mapped["Device | None"] = relationship()
