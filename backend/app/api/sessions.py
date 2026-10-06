"""Session endpoints.

Preserves the documented contract exactly:
    POST /api/sessions
    POST /api/sessions/{id}/end
    GET  /api/sessions?patient_id=
    GET  /api/sessions/{id}
    GET  /api/sessions/{id}/metrics
    GET  /api/sessions/{id}/reps
    GET  /api/sessions/{id}/report
    GET  /api/sessions/{id}/report.csv

and adds /replay, which the workspace's Movement Replay consumes.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Query, Response, status, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from app.core.exceptions import Conflict, Forbidden, SessionNotFound
from app.db.models.session import (
    ExerciseType,
    MetricSnapshot,
    RepEvent,
    RiskFlag,
    Session as SessionModel,
    SessionStatus,
)
from app.schemas.common import Page
from app.schemas.session import (
    SimulateRequest,
    MetricSnapshotPublic,
    RepEventPublic,
    RiskFlagPublic,
    SessionCreate,
    SessionDetail,
    SessionEnd,
    SessionPublic,
)
from app.services import authz, report_service, sensing_service, session_service, sim_runner
from app.services.hw_registry import hw_registry
from app.services.live_registry import registry

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _detail(db, user, session: SessionModel) -> SessionDetail:
    """Serialise a session, gating the clinician-only sections by role."""
    detail = SessionDetail.model_validate(session, from_attributes=True)
    detail.patient = (
        {
            "id": session.patient.id,
            "name": session.patient.name,
            "operated_leg": session.patient.operated_leg.value,
        }
        if session.patient
        else None
    )
    if not authz.can_view_clinical_detail(db, user, session.patient):
        # Signal diagnostics are clinician-only, withheld at the server.
        detail.data_quality = None
    return detail


def _authorised_session(db, user, session_id: int) -> SessionModel:
    session = session_service.get_session(db, session_id)
    patient = session.patient
    if patient is None or not authz.can_view_patient(db, user, patient):
        raise SessionNotFound()
    return session


@router.post("", response_model=SessionPublic, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, payload.patient_id)
    if not authz.can_edit_patient(db, user, patient):
        raise Forbidden("Only an assigned clinician may start a session.")
    session = session_service.create_session(
        db, patient=patient, exercise_type=payload.exercise_type,
        actor=user, idempotency_key=payload.idempotency_key,
    )
    db.commit()
    db.refresh(session)
    return SessionPublic.model_validate(session)


@router.get("", response_model=Page[SessionPublic])
def list_sessions(
    user: CurrentUser,
    db: DbDep,
    patient_id: int | None = Query(default=None),
    status_filter: SessionStatus | None = Query(default=None, alias="status"),
    exercise_type: ExerciseType | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if start_date and end_date and start_date > end_date:
        from app.core.exceptions import BadRequest

        raise BadRequest("start_date must not be after end_date")
    allowed = authz.visible_patient_ids(db, user)
    if patient_id is not None:
        authz.get_patient_or_403(db, user, patient_id)
    rows, total = session_service.list_sessions(
        db, patient_ids=allowed, patient_id=patient_id, status=status_filter,
        exercise_type=exercise_type, start_date=start_date, end_date=end_date,
        limit=limit, offset=offset,
    )
    return Page[SessionPublic](
        items=[SessionPublic.model_validate(s) for s in rows],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: int, user: CurrentUser, db: DbDep):
    return _detail(db, user, _authorised_session(db, user, session_id))


@router.post("/{session_id}/simulate")
async def start_simulated_stream(
    session_id: int, payload: SimulateRequest, request: Request, user: CurrentUser, db: DbDep
):
    """Start a simulated sensor stream for this session.

    The simulator is launched as an ordinary client of `/ws/ingest`, so this
    exercises the real ingestion, calibration and analytics path rather than
    a shortcut for the UI. It exists because a browser cannot start a sensor.
    """
    session = _authorised_session(db, user, session_id)
    if not authz.can_edit_patient(db, user, session.patient):
        raise Forbidden("Only an assigned clinician may stream into this session.")
    if session.status is not SessionStatus.ACTIVE:
        raise Conflict("This session is not active.")
    if sim_runner.is_running(session_id):
        raise Conflict("A simulated stream is already running for this session.")

    # The simulator connects back to this server, whatever port it is on.
    host = f"{request.url.hostname}:{request.url.port or 8000}"
    operated = session.patient.operated_leg.value if session.patient.operated_leg else "LEFT"
    try:
        sim_runner.start(
            session_id,
            host=host,
            scenario=payload.scenario,
            operated_leg=operated,
            exercise=session.exercise_type.value,
            duration_s=payload.duration_s,
            seed=payload.seed,
        )
    except RuntimeError as exc:
        raise Conflict(str(exc))

    return {
        "started": True,
        "session_id": session_id,
        "scenario": payload.scenario,
        "duration_s": payload.duration_s,
        "source": "SIMULATED",
        "note": (
            "A simulated sensor stream is connecting through the same ingestion "
            "socket physical hardware uses. No device is attached."
        ),
    }


@router.delete("/{session_id}/simulate", status_code=status.HTTP_204_NO_CONTENT)
def stop_simulated_stream(session_id: int, user: CurrentUser, db: DbDep) -> None:
    session = _authorised_session(db, user, session_id)
    if not authz.can_edit_patient(db, user, session.patient):
        raise Forbidden("Only an assigned clinician may stop this stream.")
    sim_runner.stop(session_id)


@router.post("/{session_id}/end", response_model=SessionDetail)
async def end_session(session_id: int, payload: SessionEnd, user: CurrentUser, db: DbDep):
    session = _authorised_session(db, user, session_id)
    if not authz.can_edit_patient(db, user, session.patient):
        raise Forbidden("Only an assigned clinician may end this session.")

    # A stream must not outlive the session it was feeding.
    sim_runner.stop(session_id)

    # The authoritative summary comes from the live processor when one exists
    # (hardware v2 or per-leg v1); otherwise from whatever was persisted.
    summary = await hw_registry.finalize(session_id)
    if summary is None:
        summary = await registry.finalize(session_id, payload.reported_pain)
    if summary is None and session.protocol_version == 2:
        summary = sensing_service.summary_from_persisted(db, session)
    if summary is None:
        summary = report_service.summary_from_persisted(db, session)

    session_service.end_session(
        db, session, summary=summary, reported_pain=payload.reported_pain,
        notes=payload.notes, actor=user,
    )
    if session.protocol_version == 2:
        # Recording metadata + integrity, computed from the stored raw samples.
        sensing_service.finalize_recording(db, session.id)
    db.commit()
    db.refresh(session)
    await registry.close(session_id)
    await hw_registry.close(session_id)
    return _detail(db, user, session)


@router.get("/{session_id}/metrics", response_model=list[MetricSnapshotPublic])
def session_metrics(session_id: int, user: CurrentUser, db: DbDep):
    _authorised_session(db, user, session_id)
    rows = db.execute(
        select(MetricSnapshot).where(MetricSnapshot.session_id == session_id)
        .order_by(MetricSnapshot.ts)
    ).scalars().all()
    return [MetricSnapshotPublic.model_validate(r) for r in rows]


@router.get("/{session_id}/reps", response_model=list[RepEventPublic])
def session_reps(session_id: int, user: CurrentUser, db: DbDep):
    _authorised_session(db, user, session_id)
    rows = db.execute(
        select(RepEvent).where(RepEvent.session_id == session_id).order_by(RepEvent.ts)
    ).scalars().all()
    return [RepEventPublic.model_validate(r) for r in rows]


@router.get("/{session_id}/risks", response_model=list[RiskFlagPublic])
def session_risks(session_id: int, user: CurrentUser, db: DbDep):
    _authorised_session(db, user, session_id)
    rows = db.execute(
        select(RiskFlag).where(RiskFlag.session_id == session_id).order_by(RiskFlag.ts)
    ).scalars().all()
    return [RiskFlagPublic.model_validate(r) for r in rows]


@router.get("/{session_id}/replay")
def session_replay(session_id: int, user: CurrentUser, db: DbDep):
    """Compact replay track for the Movement Replay view.

    Built from stored snapshots and events — no raw 100 Hz waveform is kept
    or reconstructed, matching the documented storage policy.
    """
    session = _authorised_session(db, user, session_id)
    return report_service.build_replay(db, session)


@router.get("/{session_id}/report")
def session_report(session_id: int, user: CurrentUser, db: DbDep):
    """Authoritative session summary, generated from persisted data."""
    session = _authorised_session(db, user, session_id)
    include_clinical = authz.can_view_clinical_detail(db, user, session.patient)
    return report_service.build_session_report(db, session, include_clinical=include_clinical)


@router.get("/{session_id}/report.csv")
def session_report_csv(session_id: int, user: CurrentUser, db: DbDep):
    session = _authorised_session(db, user, session_id)
    report = report_service.build_session_report(db, session, include_clinical=False)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["RehabSense session report"])
    writer.writerow(["Estimated decision-support indicators. Not clinical measurements."])
    writer.writerow([])
    writer.writerow(["Field", "Value"])
    for key, value in report["metrics"].items():
        writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(["Repetition", "Leg", "ROM (deg)", "Duration (s)", "Quality"])
    for rep in report["repetitions"]:
        writer.writerow([rep["rep_index"], rep["leg"], rep["rom_deg"], rep["duration_s"], rep["quality_score"]])

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="rehabsense-session-{session_id}.csv"'},
    )
