"""Hardware-v2 sensing and ML records.

    device_calibrations     the 8-check calibration, per device per wearing
    sensor_sample_chunks    raw dual-IMU + force samples, compressed ~1 s blocks,
                            with an expiry date (retention policy)
    activity_results        one row per inference window
    movement_assessments    periodic window assessments + one SESSION row
    repetition_results      one row per detected repetition / gait cycle
    model_versions          registry of trained model bundles
    session_labels          therapist labels on time ranges (future training data)
    patient_baselines       personal baseline for "change from baseline"
    data_use_consents       consent to use a patient's recordings for training

On storage growth: at 100 Hz a 13-channel stream is ~5 MB/hour as float32
before compression. One row per sample would be ~360k rows/hour/session with
per-row overhead several times the payload, so samples are stored as
compressed blocks of about one second. Every chunk carries `expires_at`
(RAW_SAMPLE_RETENTION_DAYS) and is deleted by the retention job unless it is
explicitly retained for training under an active consent.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.base import TimestampMixin


class CalibrationOutcome(str, enum.Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class DeviceCalibration(Base, TimestampMixin):
    __tablename__ = "device_calibrations"
    __table_args__ = (Index("ix_devcal_device_created", "device_pk", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_pk: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[CalibrationOutcome] = mapped_column(Enum(CalibrationOutcome), nullable=False)
    quality: Mapped[float | None] = mapped_column(Float)
    sampling_rate_declared: Mapped[float | None] = mapped_column(Float)
    sampling_rate_measured: Mapped[float | None] = mapped_column(Float)
    firmware_version: Mapped[str | None] = mapped_column(String(40))
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    calibration_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # Offsets, orientation, per-check results and thresholds (see
    # app/sensing/calibration.py: DeviceCalibrator.metadata()).
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # 1, 2, ... within a session: a recalibration is a new row, never an edit.
    sequence: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    # Session-relative time span of the samples it was computed from, so it
    # can be recomputed from the stored raw chunks (reproducibility).
    t_start: Mapped[float | None] = mapped_column(Float)
    t_end: Mapped[float | None] = mapped_column(Float)
    # Set when it stops applying: recalibrated, device reconnected, ...
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidation_reason: Mapped[str | None] = mapped_column(String(200))


class SensorSampleChunk(Base):
    __tablename__ = "sensor_sample_chunks"
    __table_args__ = (
        UniqueConstraint("session_id", "chunk_index", name="uq_chunk_per_session"),
        Index("ix_chunk_expiry", "expires_at", "retain_for_training"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    device_pk: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Session-relative seconds (device clock, first accepted sample = 0).
    t_start: Mapped[float] = mapped_column(Float, nullable=False)
    t_end: Mapped[float] = mapped_column(Float, nullable=False)
    n_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    # Column names and units, so a chunk can be decoded without the code
    # that wrote it.
    columns: Mapped[list] = mapped_column(JSON, nullable=False)
    encoding: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Raw values, *not* calibrated: the calibration row is stored separately
    # so a better calibration can be re-applied later.
    calibration_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_calibrations.id", ondelete="SET NULL")
    )
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retain_for_training: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Device clock value of session time 0 (device_ts = t + device_t0).
    device_t0: Mapped[float | None] = mapped_column(Float)
    firmware_version: Mapped[str | None] = mapped_column(String(40))
    # One entry per received packet: [first_seq, n_samples, server_receive_unix,
    # device_sent_ts or null]. Lets packet timing and loss be audited later.
    packet_log: Mapped[list | None] = mapped_column(JSON)


class InferenceStatus(str, enum.Enum):
    OK = "OK"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class ActivityResult(Base):
    __tablename__ = "activity_results"
    __table_args__ = (Index("ix_activity_session_t", "session_id", "t_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    t_start: Mapped[float] = mapped_column(Float, nullable=False)
    t_end: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[InferenceStatus] = mapped_column(Enum(InferenceStatus), nullable=False)
    # Only set when status is OK; the top candidate is kept separately so a
    # low-confidence guess is never mistaken for a prediction.
    activity: Mapped[str | None] = mapped_column(String(40))
    candidate: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float | None] = mapped_column(Float)
    probabilities: Mapped[dict | None] = mapped_column(JSON)
    model_ref: Mapped[str | None] = mapped_column(String(80))
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    inference_ms: Mapped[float | None] = mapped_column(Float)


class AssessmentKind(str, enum.Enum):
    WINDOW = "WINDOW"
    SESSION = "SESSION"


class MovementAssessment(Base):
    __tablename__ = "movement_assessments"
    __table_args__ = (Index("ix_assessment_session_t", "session_id", "t_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[AssessmentKind] = mapped_column(Enum(AssessmentKind), nullable=False)
    t_start: Mapped[float] = mapped_column(Float, nullable=False)
    t_end: Mapped[float] = mapped_column(Float, nullable=False)
    mqi: Mapped[float | None] = mapped_column(Float)
    mqi_confidence: Mapped[float | None] = mapped_column(Float)
    asymmetry_score: Mapped[float | None] = mapped_column(Float)
    asymmetry_confidence: Mapped[float | None] = mapped_column(Float)
    bilateral: Mapped[dict | None] = mapped_column(JSON)
    force_motion: Mapped[dict | None] = mapped_column(JSON)
    phase: Mapped[dict | None] = mapped_column(JSON)
    quality: Mapped[dict | None] = mapped_column(JSON)
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)


class RepetitionResult(Base):
    __tablename__ = "repetition_results"
    __table_args__ = (
        UniqueConstraint("session_id", "side", "rep_index", name="uq_hw_rep"),
        Index("ix_hw_rep_session_t", "session_id", "t_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # repetition | gait_cycle
    rep_index: Mapped[int] = mapped_column(Integer, nullable=False)
    t_start: Mapped[float] = mapped_column(Float, nullable=False)
    t_peak: Mapped[float] = mapped_column(Float, nullable=False)
    t_end: Mapped[float] = mapped_column(Float, nullable=False)
    rom_proxy_deg: Mapped[float] = mapped_column(Float, nullable=False)
    peak_velocity_dps: Mapped[float | None] = mapped_column(Float)
    smoothness_sparc: Mapped[float | None] = mapped_column(Float)
    force_peak: Mapped[float | None] = mapped_column(Float)
    force_peak_lag_s: Mapped[float | None] = mapped_column(Float)
    phase_durations: Mapped[dict | None] = mapped_column(JSON)
    detector_version: Mapped[str] = mapped_column(String(32), nullable=False)


class ModelVersion(Base, TimestampMixin):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    task: Mapped[str] = mapped_column(String(40), nullable=False)
    model_type: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(500), nullable=False)
    model_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(32), nullable=False)
    preprocessing_version: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    training_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    # {"public_dataset": "...", "rehabsense_hardware": "NOT_VALIDATED",
    #  "clinical": "NOT_VALIDATED"}
    validation_status: Mapped[dict] = mapped_column(JSON, nullable=False)
    trained_at: Mapped[str | None] = mapped_column(String(40))


class SessionLabel(Base, TimestampMixin):
    """A therapist's label on part of a recorded session.

    Only labels that can be given reliably by an observer are offered:
    exercise type, repetition number, side, movement phase, and a coarse
    quality rating against a written rubric. No diagnostic labels.
    """

    __tablename__ = "session_labels"
    __table_args__ = (Index("ix_label_session_t", "session_id", "t_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    labeller_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    t_start: Mapped[float] = mapped_column(Float, nullable=False)
    t_end: Mapped[float] = mapped_column(Float, nullable=False)
    exercise_type: Mapped[str | None] = mapped_column(String(40))
    activity: Mapped[str | None] = mapped_column(String(40))
    repetition_index: Mapped[int | None] = mapped_column(Integer)
    side: Mapped[str | None] = mapped_column(String(8))
    movement_phase: Mapped[str | None] = mapped_column(String(16))
    # 1-5 against docs/LABELLING_GUIDE.md; null when not rated.
    quality_rating: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    # Always a human. Model predictions live in activity_results /
    # repetition_results and never become labels.
    source: Mapped[str] = mapped_column(String(16), default="THERAPIST", nullable=False)
    # SILVER: one human. GOLD: confirmed by a second, different human.
    tier: Mapped[str] = mapped_column(String(8), default="SILVER", server_default="SILVER", nullable=False)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PatientBaseline(Base, TimestampMixin):
    __tablename__ = "patient_baselines"
    __table_args__ = (Index("ix_baseline_patient_active", "patient_id", "active"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    exercise_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_session_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ConsentScope(str, enum.Enum):
    # Recordings may be de-identified and used to train/evaluate models.
    MODEL_TRAINING = "MODEL_TRAINING"


class DataUseConsent(Base, TimestampMixin):
    """Consent to use a patient's recordings beyond their own care.

    Training export requires an active (granted, not revoked) row. Revoking
    clears `retain_for_training` on that patient's chunks so they fall back
    under the normal retention policy.
    """

    __tablename__ = "data_use_consents"
    __table_args__ = (Index("ix_consent_patient_scope", "patient_id", "scope"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[ConsentScope] = mapped_column(Enum(ConsentScope), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Reference to the signed consent document held elsewhere. Never the
    # document itself.
    document_ref: Mapped[str | None] = mapped_column(String(200))


class SessionMarker(Base):
    """A timestamped event mark during a recording (research mode).

    `t_session` is session time on the device clock, derived from the last
    sample the server had received when the mark arrived; `server_ts` is the
    wall-clock time it arrived. Both are kept because they answer different
    questions.
    """

    __tablename__ = "session_markers"
    __table_args__ = (Index("ix_marker_session_t", "session_id", "t_session"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    t_session: Mapped[float | None] = mapped_column(Float)
    server_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    # Event vocabulary (app/sensing/recording.py MARKER_KINDS).
    kind: Mapped[str] = mapped_column(String(32), default="note", server_default="note", nullable=False)
    # DEVICE | SERVER | USER | MODEL -- who produced it.
    source: Mapped[str] = mapped_column(String(8), default="USER", server_default="USER", nullable=False)
    # DEVICE_TIME (stamped by the device) or SERVER_RECEIVE_TIME_MAPPED (a
    # server/user event mapped onto the device timeline, with uncertainty).
    time_basis: Mapped[str] = mapped_column(String(32), default="SERVER_RECEIVE_TIME_MAPPED",
                                            server_default="SERVER_RECEIVE_TIME_MAPPED", nullable=False)
    t_uncertainty_s: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Recording(Base, TimestampMixin):
    """One continuous protocol-v2 recording (one per session).

    The raw samples are the stored chunks; this row is their metadata,
    provenance and integrity verdict. `metadata_json` is computed when the
    session ends and is what the research export's metadata.json contains.
    """

    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    recording_uid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[str] = mapped_column(String(24), nullable=False)
    device_pk: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    device_id: Mapped[str | None] = mapped_column(String(80))
    firmware_version: Mapped[str | None] = mapped_column(String(40))
    protocol_version: Mapped[int | None] = mapped_column(Integer)
    sampling_config: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    integrity: Mapped[dict | None] = mapped_column(JSON)
    # PASS / FAIL / NOT_CHECKED. A FAIL is flagged, never repaired in place.
    integrity_status: Mapped[str] = mapped_column(String(12), default="NOT_CHECKED", nullable=False)


class RecordingArtifact(Base, TimestampMixin):
    """A file in object storage that belongs to a recording.

    The bytes live in object storage (app/services/storage.py); this row is
    the durable record of where they are and what they must hash to.
    """

    __tablename__ = "recording_artifacts"
    __table_args__ = (Index("ix_artifact_recording_kind", "recording_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[int] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False
    )
    # EXPORT_ZIP (research export) | RAW_ARCHIVE (samples.npz of the raw chunks)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    export_version: Mapped[str | None] = mapped_column(String(32))
    deidentified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class LiveSnapshot(Base):
    """The latest validation inputs of a session that is streaming right now.

    Live state lives in the memory of the one API instance receiving the
    device's stream. On a host that runs several instances, a dashboard poll
    can land on another one; this row (written every few seconds by the
    receiving instance) lets any instance answer with recent figures instead
    of "not found". Deleted with its session.
    """

    __tablename__ = "live_snapshots"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
