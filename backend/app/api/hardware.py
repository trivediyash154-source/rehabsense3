"""Hardware-v2 (dual-IMU + force) endpoints.

    POST /sessions/{id}/simulate-hardware     start the v2 simulator (DEV)
    GET  /sessions/{id}/analysis              v2 session analysis, persisted rows
    GET  /sessions/{id}/activity              activity timeline (inference windows)
    GET  /sessions/{id}/calibration           stored calibration record(s)
    GET  /sessions/{id}/recording             raw-recording metadata
    GET  /sessions/{id}/recording.csv         raw samples (assigned clinician only)
    GET  /sessions/{id}/labels                therapist labels
    POST /sessions/{id}/labels                add a label (assigned clinician)
    DELETE /sessions/{id}/labels/{label_id}
    GET  /patients/{id}/baseline              active baseline + change from it
    POST /patients/{id}/baseline              set baseline from session(s)
    GET  /patients/{id}/consent               training-data consent state
    PUT  /patients/{id}/consent               grant / revoke
    GET  /ml/models                           loaded bundles + registered versions
    GET  /ml/pipeline                         measured stage latencies
    POST /ml/retention/purge                  run the raw-sample retention job (admin)

Authorisation reuses the same server-side rules as every other route: a
record the caller may not see is reported as not found.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from itertools import groupby

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import Integer, cast, func, select

from app.api.deps import CurrentUser, DbDep
from app.core.config import get_settings
from app.core.exceptions import BadRequest, Conflict, Forbidden, NotFound
from app.db.models.audit import AuditAction
from app.db.models.base import utc_iso
from app.db.models.sensing import (
    ActivityResult,
    AssessmentKind,
    ConsentScope,
    DataUseConsent,
    DeviceCalibration,
    ModelVersion,
    MovementAssessment,
    PatientBaseline,
    RepetitionResult,
    SensorSampleChunk,
    SessionLabel,
)
from app.db.models.session import Session as SessionModel, SessionStatus
from app.schemas.session import (
    MarkerCreate,
    ResearchRecordingCreate,
    BaselineCreate,
    ConsentUpdate,
    SessionLabelCreate,
    SimulateHardwareRequest,
)
from app.sensing import baseline as baseline_mod
from app.sensing import model_store
from app.sensing.processor import PIPELINE_VERSION
from app.services import audit_service, authz, sensing_service, sim_runner
from app.services.hw_registry import hw_registry

router = APIRouter(tags=["hardware"])


def _session(db, user, session_id: int) -> SessionModel:
    return authz.authorised_session(db, user, session_id)


def _require_edit(db, user, session: SessionModel) -> None:
    if not authz.can_edit_patient(db, user, session.patient):
        raise Forbidden("Only an assigned clinician may do this.")


# --------------------------------------------------------------------- #
# simulator
# --------------------------------------------------------------------- #

@router.post("/sessions/{session_id}/simulate-hardware")
async def simulate_hardware(session_id: int, payload: SimulateHardwareRequest, request: Request,
                            user: CurrentUser, db: DbDep):
    """Run the dual-IMU simulator into this session (development only).

    The simulator connects to `/ws/ingest/v2`, the socket the ESP32 uses, and
    declares itself `simulated: true`, so the session is labelled SIMULATED.
    """
    settings = get_settings()
    if not settings.allow_simulated_devices:
        raise Forbidden("Simulated devices are disabled on this server.")
    session = _session(db, user, session_id)
    _require_edit(db, user, session)
    if session.status is not SessionStatus.ACTIVE:
        raise Conflict("This session is not active.")
    if session.protocol_version == 1:
        raise Conflict("This session already holds protocol v1 data.")
    if sim_runner.is_running(session_id):
        raise Conflict("A simulated stream is already running for this session.")
    host = sim_runner.loopback_host(request)
    try:
        sim_runner.start_hardware(
            session_id, host=host, scenario=payload.scenario,
            exercise=session.exercise_type.value, duration_s=payload.duration_s,
            seed=payload.seed, device_key=settings.device_ingest_key,
        )
    except RuntimeError as exc:
        raise Conflict(str(exc))
    return {
        "started": True, "session_id": session_id, "scenario": payload.scenario,
        "duration_s": payload.duration_s, "protocol_version": 2, "source": "SIMULATED",
        "note": "SIMULATED DATA through the real v2 ingestion socket. No device is attached.",
    }


# --------------------------------------------------------------------- #
# research recording
# --------------------------------------------------------------------- #

@router.post("/research/recordings", status_code=status.HTTP_201_CREATED)
def start_research_recording(payload: ResearchRecordingCreate, user: CurrentUser, db: DbDep):
    """Open a RESEARCH session: raw LEFT/RIGHT IMU + force + timestamps + seq.

    Requires active MODEL_TRAINING consent, because a research recording
    exists to become (de-identified) training/evaluation data. Its raw chunks
    are retained only if the stream also comes from a registered,
    authenticated device; otherwise they expire like any other recording.
    """
    from app.db.models.session import ExerciseType, RecordingMode
    from app.sensing.pilot import PILOT_PROTOCOL
    from app.services import session_service

    patient = authz.get_patient_or_403(db, user, payload.patient_id)
    if not authz.can_edit_patient(db, user, patient):
        raise Forbidden("Only an assigned clinician may start a research recording.")
    if not sensing_service.has_training_consent(db, patient.id):
        raise Conflict("Research recording needs an active MODEL_TRAINING consent for this patient.")
    session = session_service.create_session(
        db, patient=patient, exercise_type=ExerciseType(payload.exercise_type), actor=user)
    session.recording_mode = RecordingMode.RESEARCH
    session.research_protocol = {
        "protocol_id": payload.protocol_id,
        "protocol_version": PILOT_PROTOCOL["version"] if payload.protocol_id == "pilot-v1" else None,
        "subject_code": payload.subject_code,
        "task": payload.task,
        "conditions": payload.conditions,
        "operator_notes": payload.operator_notes,
    }
    audit_service.record(db, action=AuditAction.RESEARCH_RECORDING_STARTED, entity_type="session",
                         entity_id=session.id, actor_id=user.id, protocol_id=payload.protocol_id)
    db.commit()
    return {"session_id": session.id, "recording_mode": "RESEARCH",
            "research_protocol": session.research_protocol,
            "ingest_path": f"/ws/ingest/v2/{session.id}",
            "note": "Raw data is retained for training only if the device is registered and "
                    "authenticated (session mode LIVE)."}


@router.post("/sessions/{session_id}/markers", status_code=status.HTTP_201_CREATED)
async def add_marker(session_id: int, payload: MarkerCreate, user: CurrentUser, db: DbDep):
    """A USER marker, mapped onto the device timeline with a stated uncertainty."""
    import time as _time

    from app.sensing.recording import MARKER_KINDS

    session = _session(db, user, session_id)
    _require_edit(db, user, session)
    kind = payload.kind or "note"
    if kind not in MARKER_KINDS:
        raise BadRequest(f"kind must be one of {', '.join(MARKER_KINDS)}")
    t, unc = await hw_registry.marker(session_id, {"label": payload.label, "kind": kind,
                                                   "note": payload.note, "source": "USER"},
                                      _time.time())
    m = sensing_service.persist_marker(db, session_id, {
        "kind": kind, "label": payload.label, "note": payload.note, "source": "USER",
        "time_basis": "SERVER_RECEIVE_TIME_MAPPED", "t_session": t, "t_uncertainty_s": unc,
    }, created_by=user.id)
    audit_service.record(db, action=AuditAction.MARKER_CREATED, entity_type="session_marker",
                         entity_id=m.id, actor_id=user.id, session_id=session_id)
    db.commit()
    return {"id": m.id, "kind": kind, "label": m.label, "source": "USER",
            "time_basis": "SERVER_RECEIVE_TIME_MAPPED", "t_session": t, "t_uncertainty_s": unc,
            "server_ts": utc_iso(m.server_ts),
            "note": None if t is not None else "No live stream: marker has no device-clock time."}


def _marker_dict(m) -> dict:
    return {"kind": m.kind, "label": m.label, "note": m.note, "source": m.source,
            "time_basis": m.time_basis, "t_session": m.t_session,
            "t_uncertainty_s": m.t_uncertainty_s, "server_ts": utc_iso(m.server_ts)}


@router.get("/sessions/{session_id}/research-record")
def research_record(session_id: int, user: CurrentUser, db: DbDep):
    """Everything needed to interpret a recording without the live system."""
    from app.db.models.sensing import SessionMarker

    session = _session(db, user, session_id)
    if not authz.can_view_clinical_detail(db, user, session.patient):
        raise Forbidden("Research records are available to the assigned clinician only.")
    markers = db.execute(select(SessionMarker).where(SessionMarker.session_id == session_id)
                         .order_by(SessionMarker.server_ts)).scalars().all()
    summary = session.summary or {}
    return {
        "session_id": session_id,
        "recording_mode": session.recording_mode.value,
        "research_protocol": session.research_protocol,
        "provenance": _provenance_of(session),
        "counts_as_hardware_evidence": session.mode.value == "LIVE",
        "exercise_type": session.exercise_type.value,
        "status": session.status.value,
        "recording": session_recording(session_id, user, db),
        "calibrations": session_calibration(session_id, user, db)["items"],
        "markers": [_marker_dict(m) for m in markers],
        "channel_layout": (summary.get("device") or {}).get("layout"),
        "stream": summary.get("stream"),
        "raw_csv": f"/api/sessions/{session_id}/recording.csv",
        "units": {"acc": "g", "gyro": "deg/s", "force": "declared per channel (adc_norm)",
                  "t": "seconds, device clock, first sample = 0"},
    }


# --------------------------------------------------------------------- #
# session analysis
# --------------------------------------------------------------------- #

def _activity_segments(rows: list[ActivityResult]) -> list[dict]:
    """Collapse consecutive windows with the same outcome into segments."""
    segments = []
    for key, group in groupby(rows, key=lambda r: (r.status.value, r.activity)):
        g = list(group)
        confs = [r.confidence for r in g if r.confidence is not None]
        segments.append({
            "status": key[0], "activity": key[1],
            "t_start": round(g[0].t_start, 2), "t_end": round(g[-1].t_end, 2),
            "windows": len(g),
            "mean_confidence": round(sum(confs) / len(confs), 3) if confs else None,
        })
    return segments


@router.get("/sessions/{session_id}/activity")
def session_activity(session_id: int, user: CurrentUser, db: DbDep,
                     limit: int = Query(default=2000, ge=1, le=20000)):
    _session(db, user, session_id)
    rows = db.execute(select(ActivityResult).where(ActivityResult.session_id == session_id)
                      .order_by(ActivityResult.t_start).limit(limit)).scalars().all()
    return {
        "session_id": session_id,
        "segments": _activity_segments(rows),
        "windows": [{"t_start": r.t_start, "t_end": r.t_end, "status": r.status.value,
                     "activity": r.activity, "candidate": r.candidate,
                     "confidence": r.confidence, "model": r.model_ref} for r in rows],
    }


@router.get("/sessions/{session_id}/calibration")
def session_calibration(session_id: int, user: CurrentUser, db: DbDep):
    _session(db, user, session_id)
    rows = db.execute(select(DeviceCalibration).where(DeviceCalibration.session_id == session_id)
                      .order_by(DeviceCalibration.sequence)).scalars().all()
    return {"items": [{"id": r.id, "sequence": r.sequence, "status": r.status.value,
                       "quality": r.quality, "simulated": r.simulated,
                       "created_at": utc_iso(r.created_at),
                       "t_start": r.t_start, "t_end": r.t_end,
                       "valid": r.invalidated_at is None,
                       "invalidated_at": utc_iso(r.invalidated_at),
                       "invalidation_reason": r.invalidation_reason,
                       "metadata": r.payload} for r in rows]}


@router.post("/sessions/{session_id}/recalibrate")
async def recalibrate(session_id: int, user: CurrentUser, db: DbDep):
    """Start a new calibration on the live device stream.

    The previous calibration is kept and marked superseded; analysis pauses
    until the new one completes.
    """
    session = _session(db, user, session_id)
    _require_edit(db, user, session)
    if not await hw_registry.recalibrate(session_id, "requested by clinician"):
        raise Conflict("No hardware stream is live for this session.")
    audit_service.record(db, action=AuditAction.CALIBRATION_INVALIDATED, entity_type="session",
                         entity_id=session_id, actor_id=user.id, reason="recalibration requested")
    db.commit()
    return {"session_id": session_id, "recalibrating": True}


@router.get("/sessions/{session_id}/analysis")
def session_analysis(session_id: int, user: CurrentUser, db: DbDep):
    """Everything the hardware pipeline recorded for one session."""
    session = _session(db, user, session_id)
    clinical = authz.can_view_clinical_detail(db, user, session.patient)
    reps = db.execute(select(RepetitionResult).where(RepetitionResult.session_id == session_id)
                      .order_by(RepetitionResult.t_start)).scalars().all()
    activity = db.execute(select(ActivityResult).where(ActivityResult.session_id == session_id)
                          .order_by(ActivityResult.t_start)).scalars().all()
    assessments = db.execute(
        select(MovementAssessment).where(MovementAssessment.session_id == session_id)
        .order_by(MovementAssessment.t_start)).scalars().all()
    session_row = next((a for a in assessments if a.kind is AssessmentKind.SESSION), None)
    summary = session.summary if (session.summary or {}).get("protocol_version") == 2 else None
    live = hw_registry.get(session_id)

    comparison = None
    if summary:
        b = sensing_service.active_baseline(db, session.patient_id, session.exercise_type.value)
        if b is not None and session_id not in (b.source_session_ids or []):
            comparison = baseline_mod.compare(
                baseline_mod.baseline_metrics_from_summary(summary), b.metrics)
            comparison["baseline_id"] = b.id

    out = {
        "session_id": session_id,
        "status": session.status.value,
        "mode": session.mode.value,
        "protocol_version": session.protocol_version,
        "exercise_type": session.exercise_type.value,
        "live": live is not None and session.status is SessionStatus.ACTIVE,
        "summary": summary,
        "repetitions": [{
            "side": r.side, "kind": r.kind, "rep_index": r.rep_index,
            "t_start": r.t_start, "t_peak": r.t_peak, "t_end": r.t_end,
            "rom_proxy_deg": r.rom_proxy_deg, "peak_velocity_dps": r.peak_velocity_dps,
            "smoothness_sparc": r.smoothness_sparc, "force_peak": r.force_peak,
            "force_peak_lag_s": r.force_peak_lag_s, "phase_durations_s": r.phase_durations,
        } for r in reps],
        "activity_segments": _activity_segments(activity),
        "assessments": [{
            "t_start": a.t_start, "t_end": a.t_end, "kind": a.kind.value, "mqi": a.mqi,
            "mqi_confidence": a.mqi_confidence, "asymmetry_score": a.asymmetry_score,
            "asymmetry_confidence": a.asymmetry_confidence,
        } for a in assessments if a.kind is AssessmentKind.WINDOW],
        "session_assessment": None if session_row is None else {
            "mqi": session_row.mqi, "asymmetry_score": session_row.asymmetry_score,
            "quality": session_row.quality, "bilateral": session_row.bilateral,
            "force_motion": session_row.force_motion,
        },
        "baseline_comparison": comparison,
        "validation": {"rehabsense_hardware": "NOT_VALIDATED", "clinical": "NOT_VALIDATED"},
    }
    if not clinical and summary:
        # Device internals are clinician-only, as for v1 sessions.
        out["summary"] = {k: v for k, v in summary.items()
                          if k not in ("calibration", "stream", "latency", "data_quality", "device")}
    return out


def _provenance_of(session: SessionModel) -> str:
    from app.sensing import provenance as prov

    return prov.of_session(session)


@router.get("/sessions/{session_id}/validation")
def session_validation(session_id: int, user: CurrentUser, db: DbDep):
    """Hardware-data validation mode: is this recording usable data?"""
    from app.sensing.validation import assess

    session = _session(db, user, session_id)
    live = hw_registry.get(session_id)
    if live is not None:
        p = live.processor
        return assess(p.monitor.as_dict(),
                      (p.calibrator.metadata() | {"stale_reason": p.calibration_stale_reason})
                      if p.calibrator.complete else None,
                      provenance=p.provenance, disconnects=p.disconnects,
                      imu_sides=list(p.layout.imu_sides)) | {"live": True}
    summary = session.summary or {}
    if summary.get("protocol_version") != 2 or "stream" not in summary:
        raise NotFound("No hardware (protocol v2) stream record for this session.")
    device = summary.get("device") or {}
    return assess(summary["stream"], summary.get("calibration"),
                  provenance=_provenance_of(session),
                  disconnects=device.get("disconnects", 0),
                  imu_sides=(device.get("layout") or {}).get("imu_sides")) | {"live": False}


# --------------------------------------------------------------------- #
# raw recording
# --------------------------------------------------------------------- #

@router.get("/sessions/{session_id}/recording")
def session_recording(session_id: int, user: CurrentUser, db: DbDep):
    _session(db, user, session_id)
    row = db.execute(select(
        func.count(SensorSampleChunk.id), func.sum(SensorSampleChunk.n_samples),
        func.max(SensorSampleChunk.t_end), func.min(SensorSampleChunk.expires_at),
        # max() over a boolean exists in SQLite but not PostgreSQL: cast first.
        func.max(cast(SensorSampleChunk.simulated, Integer)),
        func.sum(func.length(SensorSampleChunk.data)),
    ).where(SensorSampleChunk.session_id == session_id)).one()
    chunks, samples, duration, expires, simulated, size = row
    retained = db.execute(select(func.count(SensorSampleChunk.id)).where(
        SensorSampleChunk.session_id == session_id,
        SensorSampleChunk.retain_for_training.is_(True))).scalar_one()
    return {
        "session_id": session_id, "chunks": chunks or 0, "samples": int(samples or 0),
        "duration_s": duration, "simulated": bool(simulated),
        "compressed_bytes": int(size or 0), "earliest_expiry": utc_iso(expires),
        "retained_for_training_chunks": retained,
        "retention_days": get_settings().raw_sample_retention_days,
    }


@router.get("/sessions/{session_id}/recording.csv")
def session_recording_csv(session_id: int, user: CurrentUser, db: DbDep):
    session = _session(db, user, session_id)
    if not authz.can_view_clinical_detail(db, user, session.patient):
        raise Forbidden("Raw sensor data is available to the assigned clinician only.")
    columns, data = sensing_service.session_samples(db, session_id)
    if not columns:
        raise NotFound("No raw samples are stored for this session.")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([f"# RehabSense raw recording, session {session_id}, mode {session.mode.value}"])
    writer.writerow(["# acc in g, gyro in deg/s, force in the channel's declared unit; "
                     "raw values, not calibrated"])
    writer.writerow(columns)
    for row in data:
        writer.writerow([f"{v:.6g}" for v in row])
    audit_service.record(db, action=AuditAction.DATASET_EXPORTED, entity_type="session",
                         entity_id=session_id, actor_id=user.id, kind="raw_csv",
                         samples=int(len(data)))
    db.commit()
    return Response(content=buffer.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="rehabsense-raw-{session_id}.csv"'})


# --------------------------------------------------------------------- #
# labels
# --------------------------------------------------------------------- #

def _label_dict(label: SessionLabel) -> dict:
    return {
        "id": label.id, "tier": label.tier, "confirmed": label.confirmed_by is not None, "t_start": label.t_start, "t_end": label.t_end,
        "exercise_type": label.exercise_type, "activity": label.activity,
        "repetition_index": label.repetition_index, "side": label.side,
        "movement_phase": label.movement_phase, "quality_rating": label.quality_rating,
        "notes": label.notes, "source": label.source, "labeller_id": label.labeller_id,
        "created_at": utc_iso(label.created_at),
    }


@router.get("/sessions/{session_id}/labels")
def list_labels(session_id: int, user: CurrentUser, db: DbDep):
    session = _session(db, user, session_id)
    if not authz.can_view_clinical_detail(db, user, session.patient):
        return {"items": []}
    rows = db.execute(select(SessionLabel).where(SessionLabel.session_id == session_id)
                      .order_by(SessionLabel.t_start)).scalars().all()
    return {"items": [_label_dict(r) for r in rows]}


@router.post("/sessions/{session_id}/labels", status_code=status.HTTP_201_CREATED)
def create_label(session_id: int, payload: SessionLabelCreate, user: CurrentUser, db: DbDep):
    session = _session(db, user, session_id)
    _require_edit(db, user, session)
    label = SessionLabel(
        session_id=session_id, labeller_id=user.id, t_start=payload.t_start, t_end=payload.t_end,
        exercise_type=payload.exercise_type.value if payload.exercise_type else None,
        activity=payload.activity, repetition_index=payload.repetition_index,
        side=payload.side.value if payload.side else None,
        movement_phase=payload.movement_phase, quality_rating=payload.quality_rating,
        notes=payload.notes,
    )
    db.add(label)
    db.flush()
    audit_service.record(db, action=AuditAction.SESSION_LABEL_CREATED, entity_type="session_label",
                         entity_id=label.id, actor_id=user.id, session_id=session_id)
    db.commit()
    return _label_dict(label)


@router.post("/sessions/{session_id}/labels/{label_id}/confirm")
def confirm_label(session_id: int, label_id: int, user: CurrentUser, db: DbDep):
    """A second, different human confirms a label: SILVER -> GOLD."""
    session = _session(db, user, session_id)
    _require_edit(db, user, session)
    label = db.get(SessionLabel, label_id)
    if label is None or label.session_id != session_id:
        raise NotFound("Label not found.")
    if label.labeller_id == user.id:
        raise Conflict("A GOLD label needs confirmation by a different person than the labeller.")
    label.tier = "GOLD"
    label.confirmed_by = user.id
    label.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    return _label_dict(label)


@router.get("/sessions/{session_id}/export.zip")
def export_zip(session_id: int, user: CurrentUser, db: DbDep, deidentify: bool = False):
    """Research export of one recording (see app/sensing/export.py).

    Every export is also written to object storage and recorded in
    recording_artifacts (URI, SHA-256, size) before it is returned.
    """
    from app.sensing.export import store_export

    session = _session(db, user, session_id)
    if not authz.can_view_clinical_detail(db, user, session.patient):
        raise Forbidden("Research exports are available to the assigned clinician only.")
    try:
        data, art = store_export(db, session_id, deidentify=deidentify, actor_id=user.id)
    except ValueError as exc:
        raise NotFound(str(exc))
    audit_service.record(db, action=AuditAction.DATASET_EXPORTED, entity_type="recording_artifact",
                         entity_id=art.id, actor_id=user.id, kind="research_zip", sha256=art.sha256)
    db.commit()
    return Response(content=data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="rehabsense-recording-{session_id}.zip"',
        "X-RehabSense-Artifact-SHA256": art.sha256})


@router.get("/sessions/{session_id}/artifacts")
def recording_artifacts(session_id: int, user: CurrentUser, db: DbDep):
    from app.db.models.sensing import Recording, RecordingArtifact

    session = _session(db, user, session_id)
    if not authz.can_view_clinical_detail(db, user, session.patient):
        raise Forbidden("Available to the assigned clinician only.")
    rec = db.execute(select(Recording).where(Recording.session_id == session_id)).scalar_one_or_none()
    if rec is None:
        return {"items": []}
    rows = db.execute(select(RecordingArtifact).where(RecordingArtifact.recording_id == rec.id)
                      .order_by(RecordingArtifact.created_at)).scalars()
    return {"recording_id": rec.recording_uid, "items": [
        {"kind": a.kind, "storage_uri": a.storage_uri, "sha256": a.sha256, "size_bytes": a.size_bytes,
         "schema_version": a.schema_version, "export_version": a.export_version,
         "deidentified": a.deidentified, "created_at": utc_iso(a.created_at)} for a in rows]}


@router.get("/sessions/{session_id}/recording-integrity")
def recording_integrity(session_id: int, user: CurrentUser, db: DbDep):
    from app.db.models.sensing import Recording

    _session(db, user, session_id)
    rec = db.execute(select(Recording).where(Recording.session_id == session_id)).scalar_one_or_none()
    if rec is None:
        raise NotFound("No protocol-v2 recording for this session.")
    return {"recording_id": rec.recording_uid, "provenance": rec.provenance,
            "integrity_status": rec.integrity_status, "integrity": rec.integrity,
            "metadata": rec.metadata_json}


@router.delete("/sessions/{session_id}/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(session_id: int, label_id: int, user: CurrentUser, db: DbDep) -> None:
    session = _session(db, user, session_id)
    _require_edit(db, user, session)
    label = db.get(SessionLabel, label_id)
    if label is None or label.session_id != session_id:
        raise NotFound("Label not found.")
    db.delete(label)
    audit_service.record(db, action=AuditAction.SESSION_LABEL_DELETED, entity_type="session_label",
                         entity_id=label_id, actor_id=user.id, session_id=session_id)
    db.commit()


# --------------------------------------------------------------------- #
# personal baseline
# --------------------------------------------------------------------- #

def _baseline_dict(b: PatientBaseline) -> dict:
    return {"id": b.id, "exercise_type": b.exercise_type, "metrics": b.metrics,
            "source_session_ids": b.source_session_ids, "pipeline_version": b.pipeline_version,
            "created_at": utc_iso(b.created_at), "label": baseline_mod.LABEL}


@router.get("/patients/{patient_id}/baseline")
def get_baseline(patient_id: int, user: CurrentUser, db: DbDep,
                 exercise_type: str = Query(...), session_id: int | None = Query(default=None)):
    patient = authz.get_patient_or_403(db, user, patient_id)
    b = sensing_service.active_baseline(db, patient.id, exercise_type)
    if session_id is not None:
        current = _session(db, user, session_id)
        if current.patient_id != patient.id:
            raise NotFound("Session not found.")
    else:
        current = db.execute(
            select(SessionModel).where(
                SessionModel.patient_id == patient.id,
                SessionModel.exercise_type == exercise_type,
                SessionModel.status == SessionStatus.COMPLETED,
                SessionModel.protocol_version == 2,
            ).order_by(SessionModel.started_at.desc())).scalars().first()
    comparison = None
    current_metrics = None
    if current is not None and (current.summary or {}).get("protocol_version") == 2:
        current_metrics = baseline_mod.baseline_metrics_from_summary(current.summary)
        if b is not None:
            comparison = baseline_mod.compare(current_metrics, b.metrics)
    return {
        "patient_id": patient.id, "exercise_type": exercise_type,
        "baseline": None if b is None else _baseline_dict(b),
        "current_session_id": None if current is None else current.id,
        "current": current_metrics,
        "comparison": comparison,
        "label": baseline_mod.LABEL,
    }


@router.post("/patients/{patient_id}/baseline", status_code=status.HTTP_201_CREATED)
def set_baseline(patient_id: int, payload: BaselineCreate, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, patient_id)
    if not authz.can_edit_patient(db, user, patient):
        raise Forbidden("Only an assigned clinician may set a baseline.")
    sessions = []
    for sid in payload.session_ids:
        s = db.get(SessionModel, sid)
        if s is None or s.patient_id != patient.id:
            raise NotFound(f"Session {sid} not found.")
        if s.status is not SessionStatus.COMPLETED or (s.summary or {}).get("protocol_version") != 2:
            raise BadRequest(f"Session {sid} is not a completed hardware (v2) session.")
        if s.mode.value != "LIVE":
            raise BadRequest(f"Session {sid} is {s.mode.value}; a baseline must come from a "
                             "registered, authenticated RehabSense device.")
        sessions.append(s)
    exercises = {s.exercise_type.value for s in sessions}
    if len(exercises) != 1:
        raise BadRequest("Baseline sessions must all be the same exercise.")
    metrics = baseline_mod.average_metrics(
        [baseline_mod.baseline_metrics_from_summary(s.summary) for s in sessions])
    if not metrics:
        raise BadRequest("The selected sessions have no comparable metrics.")
    exercise = exercises.pop()
    for old in db.execute(select(PatientBaseline).where(
            PatientBaseline.patient_id == patient.id, PatientBaseline.exercise_type == exercise,
            PatientBaseline.active.is_(True))).scalars():
        old.active = False
    b = PatientBaseline(patient_id=patient.id, created_by=user.id, exercise_type=exercise,
                        source_session_ids=[s.id for s in sessions], metrics=metrics,
                        pipeline_version=PIPELINE_VERSION, active=True)
    db.add(b)
    db.flush()
    audit_service.record(db, action=AuditAction.BASELINE_SET, entity_type="patient_baseline",
                         entity_id=b.id, actor_id=user.id, patient_id=patient.id,
                         sessions=[s.id for s in sessions])
    db.commit()
    return _baseline_dict(b)


# --------------------------------------------------------------------- #
# consent
# --------------------------------------------------------------------- #

def _consent_state(db, patient_id: int) -> dict:
    row = db.execute(select(DataUseConsent).where(
        DataUseConsent.patient_id == patient_id,
        DataUseConsent.scope == ConsentScope.MODEL_TRAINING,
    ).order_by(DataUseConsent.created_at.desc(), DataUseConsent.id.desc())).scalars().first()
    return {
        "scope": ConsentScope.MODEL_TRAINING.value,
        "granted": bool(row and row.granted and row.revoked_at is None),
        "granted_at": None if row is None else utc_iso(row.granted_at),
        "revoked_at": None if row is None else utc_iso(row.revoked_at),
        "document_ref": None if row is None else row.document_ref,
        "explanation": (
            "When granted, this patient's recordings from registered, authenticated "
            "RehabSense devices may be "
            "de-identified and used to train and evaluate RehabSense models. Without it, "
            "recordings are used only for this patient's own sessions and expire under the "
            "raw-data retention policy."
        ),
    }


@router.get("/patients/{patient_id}/consent")
def get_consent(patient_id: int, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, patient_id)
    return _consent_state(db, patient.id)


@router.put("/patients/{patient_id}/consent")
def put_consent(patient_id: int, payload: ConsentUpdate, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, patient_id)
    # The patient themselves, or an assigned clinician recording it.
    if not (authz.owns_patient(db, user, patient) or authz.can_edit_patient(db, user, patient)):
        raise Forbidden("Only the patient or an assigned clinician may record consent.")
    now = datetime.now(timezone.utc)
    if payload.granted:
        db.add(DataUseConsent(patient_id=patient.id, scope=ConsentScope.MODEL_TRAINING,
                              granted=True, granted_at=now, recorded_by=user.id,
                              document_ref=payload.document_ref))
        changed = sensing_service.set_training_retention(db, patient.id, True)
        action = AuditAction.CONSENT_RECORDED
    else:
        db.add(DataUseConsent(patient_id=patient.id, scope=ConsentScope.MODEL_TRAINING,
                              granted=False, revoked_at=now, recorded_by=user.id,
                              document_ref=payload.document_ref))
        changed = sensing_service.set_training_retention(db, patient.id, False)
        action = AuditAction.CONSENT_REVOKED
    audit_service.record(db, action=action, entity_type="patient", entity_id=patient.id,
                         actor_id=user.id, chunks_updated=changed)
    db.commit()
    return _consent_state(db, patient.id)


# --------------------------------------------------------------------- #
# models, pipeline, retention
# --------------------------------------------------------------------- #

def ml_status_block(db, loaded: dict) -> dict:
    """The ML status headline, derived from the loaded bundles' own validation
    metadata and the database -- never asserted. Hardware and clinical
    validation can only read YES if a deployed bundle records it."""
    from app.db.models.sensing import Recording

    bundles = [b for b in loaded.values() if b.get("loaded", True) is not False]
    vs = [b.get("validation_status") or {} for b in bundles]
    human_labeled = db.execute(
        select(func.count(func.distinct(Recording.id)))
        .join(SessionLabel, SessionLabel.session_id == Recording.session_id)
        .where(Recording.provenance == "PHYSICAL_REGISTERED")
    ).scalar_one()
    yes = lambda cond: "YES" if cond else "NO"  # noqa: E731
    return {
        "MODEL_IMPLEMENTED": yes(bool(bundles)),
        "PUBLIC_DATASET_VALIDATED": yes(bool(vs) and all(
            str(v.get("public_dataset", "")).startswith("EVALUATED") for v in vs)),
        "REAL_REHABSENSE_HARDWARE_VALIDATED": yes(bool(vs) and all(
            v.get("rehabsense_hardware") == "VALIDATED" for v in vs)),
        "HUMAN_LABELED_PHYSICAL_DATA": int(human_labeled),
        "CLINICAL_VALIDATION": yes(bool(vs) and all(v.get("clinical") == "VALIDATED" for v in vs)),
    }


@router.get("/ml/models")
def ml_models(user: CurrentUser, db: DbDep):
    rows = db.execute(select(ModelVersion).order_by(ModelVersion.name, ModelVersion.created_at)).scalars()
    loaded = model_store.status()
    return {
        "status_block": ml_status_block(db, loaded),
        "loaded": loaded,
        "registered": [{
            "name": r.name, "version": r.version, "task": r.task, "model_type": r.model_type,
            "feature_version": r.feature_version, "metrics": r.metrics, "dataset": r.dataset,
            "validation_status": r.validation_status, "trained_at": r.trained_at,
        } for r in rows],
        "validation_note": (
            "Public-dataset performance is not RehabSense hardware performance, and neither "
            "is clinical validation. Hardware and clinical validation: NOT VALIDATED."
        ),
    }


@router.get("/ml/pipeline")
def ml_pipeline(user: CurrentUser):
    if not authz.is_clinician(user):
        raise Forbidden("Pipeline diagnostics are available to clinicians and admins.")
    return {**hw_registry.stats(), "note": (
        "Measured with perf_counter on this server. Sensor-to-backend latency is relative "
        "to the fastest packet observed; absolute one-way latency needs synchronised clocks.")}


@router.get("/ml/pilot-status")
def pilot_status(user: CurrentUser, db: DbDep):
    """Progress of the real-hardware pilot collection against the protocol.

    Counts only sessions from registered, authenticated devices (mode LIVE). A
    session counts toward the dataset only if its patient consented, its
    validation verdict is usable, and it has therapist labels.
    """
    from app.sensing.pilot import PILOT_PROTOCOL
    from app.sensing.validation import assess

    if not authz.is_clinician(user):
        raise Forbidden("Pilot status is available to clinicians and admins.")
    allowed = authz.visible_patient_ids(db, user)
    q = select(SessionModel).where(SessionModel.protocol_version == 2,
                                   SessionModel.status == SessionStatus.COMPLETED)
    if allowed is not None:
        q = q.where(SessionModel.patient_id.in_(allowed or [-1]))
    rows = db.execute(q).scalars().all()
    simulated = [s for s in rows if s.mode.value == "SIMULATED"]
    unverified = [s for s in rows if s.mode.value not in ("SIMULATED", "LIVE")]
    real = [s for s in rows if s.mode.value == "LIVE"]
    per_subject: dict[int, dict] = {}
    for s in real:
        summary = s.summary or {}
        device = summary.get("device") or {}
        verdict = None
        if "stream" in summary:
            verdict = assess(summary["stream"], summary.get("calibration"),
                             provenance="PHYSICAL_REGISTERED",
                             disconnects=device.get("disconnects", 0),
                             imu_sides=(device.get("layout") or {}).get("imu_sides"))["verdict"]
        labels = db.execute(select(func.count(SessionLabel.id)).where(
            SessionLabel.session_id == s.id)).scalar_one()
        consented = sensing_service.has_training_consent(db, s.patient_id)
        entry = per_subject.setdefault(s.patient_id, {"consented": consented, "exercises": {}})
        ex = entry["exercises"].setdefault(s.exercise_type.value,
                                           {"sessions": 0, "usable": 0, "labelled": 0, "dataset_ready": 0})
        ex["sessions"] += 1
        usable = verdict in ("USABLE", "USABLE_WITH_WARNINGS")
        ex["usable"] += int(usable)
        ex["labelled"] += int(labels > 0)
        ex["dataset_ready"] += int(usable and labels > 0 and consented)
    ready_subjects = sum(
        1 for v in per_subject.values()
        if v["consented"] and all(
            v["exercises"].get(e, {}).get("dataset_ready", 0) >= PILOT_PROTOCOL["sessions_per_subject"]
            for e in PILOT_PROTOCOL["exercises"]))
    return {
        "protocol": PILOT_PROTOCOL,
        "real_sessions": len(real),
        "simulated_sessions_excluded": len(simulated),
        "unverified_sessions_excluded": len(unverified),
        "subjects_with_real_data": len(per_subject),
        "subjects_complete": ready_subjects,
        "per_subject": {f"patient_{k}": v for k, v in per_subject.items()},
        "hardware_validation_possible": ready_subjects >= 3,
        "note": "Hardware validation of any model requires dataset-ready sessions from "
                "subjects never used in training. Simulated sessions never count.",
    }


@router.get("/ml/label-inventory")
def label_inventory(user: CurrentUser, db: DbDep):
    """Human labels vs model outputs, by provenance. Never manufactures a gold set."""
    from app.db.models.sensing import Recording

    if not authz.is_clinician(user):
        raise Forbidden("Available to clinicians and admins.")
    recs = db.execute(select(Recording)).scalars().all()
    out = {p: {"recordings": 0, "human_labeled": 0, "gold": 0, "silver": 0, "unlabeled": 0}
           for p in ("PHYSICAL_REGISTERED", "PHYSICAL_UNVERIFIED", "SIMULATED", "PUBLIC_DATASET_REPLAY")}
    for r in recs:
        labels = db.execute(select(SessionLabel).where(SessionLabel.session_id == r.session_id)).scalars().all()
        row = out.setdefault(r.provenance, {"recordings": 0, "human_labeled": 0, "gold": 0,
                                            "silver": 0, "unlabeled": 0})
        row["recordings"] += 1
        tiers = {l.tier for l in labels}
        if labels:
            row["human_labeled"] += 1
        row["gold" if "GOLD" in tiers else "silver" if labels else "unlabeled"] += 1
    physical = out["PHYSICAL_REGISTERED"]
    return {
        "HUMAN_LABELED_PHYSICAL_RECORDINGS": physical["human_labeled"],
        "GOLD_PHYSICAL_RECORDINGS": physical["gold"],
        "by_provenance": out,
        "categories": {"GOLD": "human label confirmed by a second human",
                       "SILVER": "single human label", "MODEL-GENERATED": "activity/repetition "
                       "predictions (never counted as labels)", "UNLABELED": "no human label"},
    }


@router.post("/ml/retention/purge")
def purge_raw(user: CurrentUser, db: DbDep):
    if not authz.is_admin(user):
        raise Forbidden("Only an administrator may run the retention job.")
    count = sensing_service.purge_expired_chunks(db)
    db.commit()
    return {"deleted_chunks": count}
