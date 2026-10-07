"""Session lifecycle and persistence of analytics output."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession, selectinload

from app.core.config import get_settings
from app.core.exceptions import SessionAlreadyCompleted, SessionNotFound
from app.db.models.audit import AuditAction
from app.db.models.patient import Leg, PatientProfile
from app.db.models.session import (
    CalibrationState,
    ExerciseType,
    MetricSnapshot,
    RepEvent,
    RiskFlag,
    RiskSeverity,
    Session as SessionModel,
    SessionDeviceLink,
    SessionMode,
    SessionStatus,
)
from app.db.models.user import User
from app.services import audit_service


def create_session(
    db: DbSession,
    *,
    patient: PatientProfile,
    exercise_type: ExerciseType,
    actor: User | None,
    idempotency_key: str | None = None,
) -> SessionModel:
    """Open a session. Retrying with the same key returns the original."""
    if idempotency_key:
        existing = db.execute(
            select(SessionModel).where(SessionModel.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing:
            return existing

    session = SessionModel(
        patient_id=patient.id,
        exercise_type=exercise_type,
        status=SessionStatus.ACTIVE,
        mode=SessionMode.UNKNOWN,
        started_at=datetime.now(timezone.utc),
        created_by=actor.id if actor else None,
        idempotency_key=idempotency_key,
        analytics_version=get_settings().analytics_version,
    )
    db.add(session)
    db.flush()

    # One link row per leg from the start, so the dashboard can show both legs
    # as DISCONNECTED rather than as missing.
    for leg in (Leg.LEFT, Leg.RIGHT):
        db.add(SessionDeviceLink(session_id=session.id, leg=leg))
    db.flush()

    audit_service.record(
        db, action=AuditAction.SESSION_STARTED, entity_type="session",
        entity_id=session.id, actor_id=actor.id if actor else None,
        patient_id=patient.id, exercise=exercise_type.value,
    )
    return session


def get_session(db: DbSession, session_id: int) -> SessionModel:
    session = db.execute(
        select(SessionModel)
        .where(SessionModel.id == session_id)
        .options(selectinload(SessionModel.device_links))
    ).scalar_one_or_none()
    if session is None:
        raise SessionNotFound()
    return session


def list_sessions(
    db: DbSession,
    *,
    patient_ids: list[int] | None,
    patient_id: int | None = None,
    status: SessionStatus | None = None,
    exercise_type: ExerciseType | None = None,
    start_date=None,
    end_date=None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SessionModel], int]:
    stmt = select(SessionModel)
    count_stmt = select(func.count(SessionModel.id))

    def apply(where):
        nonlocal stmt, count_stmt
        stmt = stmt.where(where)
        count_stmt = count_stmt.where(where)

    if patient_ids is not None:
        if not patient_ids:
            return [], 0
        apply(SessionModel.patient_id.in_(patient_ids))
    if patient_id is not None:
        apply(SessionModel.patient_id == patient_id)
    if status is not None:
        apply(SessionModel.status == status)
    if exercise_type is not None:
        apply(SessionModel.exercise_type == exercise_type)
    if start_date is not None:
        apply(SessionModel.started_at >= start_date)
    if end_date is not None:
        apply(SessionModel.started_at <= end_date)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(SessionModel.started_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return list(rows), total


def end_session(
    db: DbSession,
    session: SessionModel,
    *,
    summary: dict,
    reported_pain: float | None = None,
    notes: str | None = None,
    actor: User | None = None,
) -> SessionModel:
    """Finalise a session with the authoritative analytics summary.

    Idempotent: ending an already-completed session returns it unchanged
    rather than overwriting the finalised numbers.
    """
    if session.status is SessionStatus.COMPLETED:
        raise SessionAlreadyCompleted()

    session.status = SessionStatus.COMPLETED
    session.ended_at = datetime.now(timezone.utc)
    if reported_pain is not None:
        session.reported_pain = reported_pain
    if notes is not None:
        session.notes = notes

    session.summary = summary
    session.confidence = summary.get("confidence")
    session.data_quality = summary.get("data_quality")
    session.analytics_version = summary.get("analytics_version", session.analytics_version)
    mode = summary.get("session_mode", "UNKNOWN")
    session.mode = SessionMode(mode) if mode in SessionMode.__members__ else SessionMode.UNKNOWN

    quality = summary.get("data_quality", {})
    if quality.get("calibration_left") == "COMPLETE" or quality.get("calibration_right") == "COMPLETE":
        session.calibration_state = CalibrationState.COMPLETE
    # Hardware v2 reports one device calibration verdict (PASS / WARN / FAIL /
    # SKIPPED) rather than one state per leg node.
    v2_status = quality.get("calibration_status")
    if v2_status in ("PASS", "WARN"):
        session.calibration_state = CalibrationState.COMPLETE
    elif v2_status == "FAIL":
        session.calibration_state = CalibrationState.FAILED
    v2_quality = (summary.get("calibration") or {}).get("quality")
    if v2_status and isinstance(v2_quality, (int, float)):
        session.calibration_quality = float(v2_quality)
    db.flush()

    audit_service.record(
        db, action=AuditAction.SESSION_ENDED, entity_type="session",
        entity_id=session.id, actor_id=actor.id if actor else None,
        duration_s=summary.get("duration_s"), repetitions=summary.get("repetitions"),
        analytics_version=session.analytics_version,
    )
    return session


# --------------------------------------------------------------------- #
# analytics persistence
# --------------------------------------------------------------------- #

def persist_metric(db: DbSession, session_id: int, payload: dict) -> MetricSnapshot:
    recovery = payload.get("recovery_score") or {}
    confidence = payload.get("confidence") or {}
    snapshot = MetricSnapshot(
        session_id=session_id,
        ts=datetime.now(timezone.utc),
        t_offset=payload.get("t_offset", 0.0),
        left_knee_angle_deg=(payload.get("left") or {}).get("knee_angle_deg"),
        right_knee_angle_deg=(payload.get("right") or {}).get("knee_angle_deg"),
        rom_running_deg=payload.get("rom_running_deg"),
        cadence_spm=payload.get("cadence_spm"),
        symmetry_index_pct=payload.get("symmetry_index_pct"),
        recovery_score=recovery.get("value"),
        recovery_confidence=confidence.get("value"),
        score_contributions={"contributions": recovery.get("contributions", [])},
    )
    db.add(snapshot)
    return snapshot


def persist_rep(db: DbSession, session_id: int, payload: dict) -> RepEvent | None:
    leg = Leg(payload["leg"])
    # The unique (session, leg, rep_index) constraint makes a replayed packet
    # a no-op rather than a duplicate repetition.
    existing = db.execute(
        select(RepEvent.id).where(
            RepEvent.session_id == session_id,
            RepEvent.leg == leg,
            RepEvent.rep_index == payload["rep_index"],
        )
    ).first()
    if existing:
        return None

    rep = RepEvent(
        session_id=session_id,
        ts=datetime.now(timezone.utc),
        t_offset=payload.get("t_offset", 0.0),
        leg=leg,
        rep_index=payload["rep_index"],
        rom_deg=payload["rom_deg"],
        peak_angle_deg=payload.get("peak_angle_deg"),
        min_angle_deg=payload.get("min_angle_deg"),
        duration_s=payload["duration_s"],
        smoothness=payload.get("smoothness"),
        quality_score=payload.get("quality_score"),
    )
    db.add(rep)
    return rep


def persist_risk(db: DbSession, session_id: int, payload: dict) -> RiskFlag:
    flag = RiskFlag(
        session_id=session_id,
        ts=datetime.now(timezone.utc),
        t_offset=payload.get("t_offset", 0.0),
        severity=RiskSeverity(payload.get("severity", "INFO")),
        message=payload["message"],
        source_metric=payload.get("source_metric"),
    )
    db.add(flag)
    return flag


def update_device_link(db: DbSession, session_id: int, leg: Leg, state: dict) -> None:
    def _existing() -> SessionDeviceLink | None:
        return db.execute(
            select(SessionDeviceLink).where(
                SessionDeviceLink.session_id == session_id, SessionDeviceLink.leg == leg
            )
        ).scalar_one_or_none()

    link = _existing()
    if link is None:
        # Both leg handlers persist concurrently, each on its own connection,
        # so two of them can pass the SELECT above before either INSERTs. Two
        # sensor nodes powering up together is the normal case, not an edge
        # case, so the unique constraint on (session_id, leg) is what keeps
        # this correct -- and losing the race must not discard the whole batch
        # of events. Insert inside a savepoint, and on collision re-read the
        # row the other writer committed.
        try:
            with db.begin_nested():
                link = SessionDeviceLink(session_id=session_id, leg=leg)
                db.add(link)
                db.flush()
        except IntegrityError:
            link = _existing()
            if link is None:
                raise

    from app.db.models.session import ConnectionState as DbConnState

    link.state = DbConnState(state["state"])
    link.packets_received = state.get("packets_received", 0)
    link.packets_dropped = state.get("packets_dropped", 0)
    link.sequence_gaps = state.get("sequence_gaps", 0)
    link.connected_seconds = state.get("connected_seconds", 0.0)
    link.fsr_available = state.get("fsr_available", False)
    link.last_seen_at = datetime.now(timezone.utc)
    if link.first_connected_at is None and state["state"] == "CONNECTED":
        link.first_connected_at = datetime.now(timezone.utc)
