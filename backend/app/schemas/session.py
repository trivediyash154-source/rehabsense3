from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.patient import Leg
from app.db.models.session import (
    CalibrationState,
    ExerciseType,
    RiskSeverity,
    SessionMode,
    SessionStatus,
)
from app.schemas.types import UtcDatetime


class SessionCreate(BaseModel):
    patient_id: int
    exercise_type: ExerciseType
    # Repeating a create with the same key returns the original session
    # instead of opening a duplicate.
    idempotency_key: str | None = Field(default=None, max_length=80)


class SessionEnd(BaseModel):
    reported_pain: float | None = Field(default=None, ge=0, le=10)
    notes: str | None = Field(default=None, max_length=4000)


class SessionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    exercise_type: ExerciseType
    status: SessionStatus
    mode: SessionMode
    started_at: UtcDatetime
    ended_at: UtcDatetime | None = None
    reported_pain: float | None = None
    notes: str | None = None
    calibration_state: CalibrationState
    analytics_version: str | None = None
    protocol_version: int | None = None
    recording_mode: str | None = None
    summary: dict | None = None
    confidence: dict | None = None


class SessionDetail(SessionPublic):
    data_quality: dict | None = None
    # Populated explicitly by the API layer, never pulled from the ORM
    # relationship, so the patient shape stays role-controlled.
    patient: dict | None = Field(default=None, exclude=False, validation_alias="__patient_dict__")


class MetricSnapshotPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: UtcDatetime
    t_offset: float
    left_knee_angle_deg: float | None = None
    right_knee_angle_deg: float | None = None
    rom_running_deg: float | None = None
    cadence_spm: float | None = None
    symmetry_index_pct: float | None = None
    recovery_score: float | None = None
    recovery_confidence: float | None = None
    score_contributions: dict | None = None


class RepEventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: UtcDatetime
    t_offset: float
    leg: Leg
    rep_index: int
    rom_deg: float
    peak_angle_deg: float | None = None
    min_angle_deg: float | None = None
    duration_s: float
    smoothness: float | None = None
    quality_score: float | None = None


class RiskFlagPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: UtcDatetime
    t_offset: float
    severity: RiskSeverity
    message: str
    source_metric: str | None = None
    acknowledged: bool
    resolved: bool


SCENARIOS = (
    "ASYMMETRY", "SEVERE_ASYMMETRY", "IMPROVING", "RECOVERY_STABLE", "RISK_EVENT",
    "LOW_CONFIDENCE", "NOISY_SENSOR", "SENSOR_DROP", "RECONNECT",
    "LEFT_DISCONNECTED", "RIGHT_DISCONNECTED", "DELAYED_START",
)


class SimulateRequest(BaseModel):
    """Start a simulated sensor stream for an active session."""

    scenario: str = "ASYMMETRY"
    # Bounded so a request cannot pin a process indefinitely.
    duration_s: int = Field(default=60, ge=5, le=900)
    seed: int | None = None

    @field_validator("scenario")
    @classmethod
    def _known_scenario(cls, value: str) -> str:
        if value not in SCENARIOS:
            raise ValueError(f"Unknown scenario. Choose one of: {', '.join(SCENARIOS)}.")
        return value


class SimulateHardwareRequest(BaseModel):
    """Start the dual-IMU (protocol v2) simulator for an active session."""

    scenario: str = "SYMMETRIC"
    duration_s: int = Field(default=60, ge=5, le=900)
    seed: int | None = None

    @field_validator("scenario")
    @classmethod
    def _known(cls, value: str) -> str:
        from app.simulator.dual_imu_simulator import SCENARIOS as HW_SCENARIOS

        if value not in HW_SCENARIOS:
            raise ValueError(f"Unknown scenario. Choose one of: {', '.join(HW_SCENARIOS)}.")
        return value


class SessionLabelCreate(BaseModel):
    """A therapist label on a time range of a recorded session."""

    t_start: float = Field(ge=0)
    t_end: float = Field(ge=0)
    exercise_type: ExerciseType | None = None
    activity: str | None = Field(default=None, max_length=40)
    repetition_index: int | None = Field(default=None, ge=1, le=10000)
    side: Leg | None = None
    movement_phase: str | None = None
    quality_rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("movement_phase")
    @classmethod
    def _phase(cls, value: str | None) -> str | None:
        from app.sensing.repetitions import PHASES

        if value is not None and value not in PHASES:
            raise ValueError(f"movement_phase must be one of {', '.join(PHASES)}")
        return value

    @field_validator("t_end")
    @classmethod
    def _order(cls, value: float, info) -> float:
        start = info.data.get("t_start")
        if start is not None and value <= start:
            raise ValueError("t_end must be after t_start")
        return value


class BaselineCreate(BaseModel):
    """Set a personal baseline from one or more completed v2 sessions."""

    session_ids: list[int] = Field(min_length=1, max_length=10)


class ConsentUpdate(BaseModel):
    granted: bool
    document_ref: str | None = Field(default=None, max_length=200)


class ResearchRecordingCreate(BaseModel):
    """Start a research recording: raw dual-IMU + force data is the product."""

    patient_id: int
    exercise_type: ExerciseType
    # Pseudonymous code from the study log (never a name). Letters, digits, - _
    subject_code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    protocol_id: str = Field(default="pilot-v1", max_length=40)
    task: str | None = Field(default=None, max_length=120)
    conditions: str | None = Field(default=None, max_length=300)
    operator_notes: str | None = Field(default=None, max_length=1000)


class MarkerCreate(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    kind: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=300)
