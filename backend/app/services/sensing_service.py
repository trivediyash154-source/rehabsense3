"""Persistence for the hardware-v2 pipeline.

Called from worker threads by the hardware registry. Every function takes its
own short-lived DB session via the caller and never raises into the live
stream: a database hiccup must not drop sensor data on the floor *and* kill
the socket.
"""

from __future__ import annotations

import zlib
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.db.models.audit import AuditAction
from app.db.models.device import Device, DeviceKind, DeviceStatus, Sensor, SensorLocation, SensorStatus, SensorType
from app.db.models.sensing import (
    ActivityResult,
    AssessmentKind,
    CalibrationOutcome,
    ConsentScope,
    DataUseConsent,
    DeviceCalibration,
    InferenceStatus,
    ModelVersion,
    MovementAssessment,
    PatientBaseline,
    RepetitionResult,
    SensorSampleChunk,
)
from app.db.models.session import Session as SessionModel
from app.sensing.processor import PIPELINE_VERSION
from app.services import audit_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------- #
# devices
# --------------------------------------------------------------------- #

_PLACEMENT_LOCATION = {
    "THIGH": SensorLocation.THIGH,
    "SHANK": SensorLocation.SHIN,
    "FOOT": SensorLocation.FOOT,
}


from app.sensing import provenance as prov  # noqa: E402

PROVENANCE_SIMULATED = prov.SIMULATED
PROVENANCE_VERIFIED = prov.PHYSICAL_REGISTERED
PROVENANCE_UNVERIFIED = prov.PHYSICAL_UNVERIFIED


def hash_device_key(key: str) -> str:
    import hashlib

    return hashlib.sha256(key.encode()).hexdigest()


def resolve_provenance(db: DbSession, hello) -> tuple[str | None, str | None]:
    """Decide where this stream comes from. Returns (provenance, refusal_code).

    * a device registered with its own key must present that key; it is then
      PHYSICAL_REGISTERED (or refused);
    * `simulated: true` is SIMULATED;
    * anything else is UNVERIFIED: omitting the simulated flag is not
      evidence of a physical device.
    """
    import hmac

    from app.db.models.base import as_utc

    device = db.execute(select(Device).where(Device.device_id == hello.device_id)).scalar_one_or_none()
    if device is not None and device.revoked_at is not None:
        return None, "DEVICE_REVOKED"
    if device is not None and device.key_hash and device.key_expires_at is not None \
            and as_utc(device.key_expires_at) < _now():
        return None, "DEVICE_KEY_EXPIRED"
    if device is not None and device.key_hash:
        presented = hash_device_key(hello.device_key or "")
        if not hmac.compare_digest(presented, device.key_hash):
            return None, "DEVICE_UNAUTHORIZED"
        if hello.simulated:
            return None, "REGISTERED_DEVICE_DECLARED_SIMULATED"
        return PROVENANCE_VERIFIED, None
    if hello.simulated:
        return (prov.PUBLIC_DATASET_REPLAY if hello.data_source == "PUBLIC_DATASET_REPLAY"
                else prov.SIMULATED), None
    if get_settings().require_registered_devices:
        return None, "DEVICE_NOT_REGISTERED"
    return PROVENANCE_UNVERIFIED, None


def register_hardware(db: DbSession, device_id: str, actor_id: int, notes: str | None,
                      expires_in_days: int | None = None) -> str:
    """Register a physical device; returns its key (shown once, stored hashed)."""
    import secrets

    device = db.execute(select(Device).where(Device.device_id == device_id)).scalar_one_or_none()
    if device is None:
        device = Device(device_id=device_id)
        db.add(device)
    key = secrets.token_urlsafe(24)
    device.key_hash = hash_device_key(key)
    device.verified_hardware = True
    device.kind = DeviceKind.HARDWARE
    device.registered_at = _now()
    device.registered_by = actor_id
    device.hardware_notes = notes
    device.revoked_at = None   # re-registration is an explicit act that lifts a revocation
    device.key_expires_at = (_now() + timedelta(days=expires_in_days)) if expires_in_days else None
    db.flush()
    audit_service.record(db, action=AuditAction.DEVICE_REGISTERED, entity_type="device",
                         entity_id=device_id, actor_id=actor_id)
    return key


def revoke_hardware(db: DbSession, device_id: str, actor_id: int) -> bool:
    device = db.execute(select(Device).where(Device.device_id == device_id)).scalar_one_or_none()
    if device is None or not device.key_hash:
        return False
    device.key_hash = None
    device.verified_hardware = False
    device.kind = DeviceKind.UNVERIFIED
    device.revoked_at = _now()
    audit_service.record(db, action=AuditAction.DEVICE_KEY_REVOKED, entity_type="device",
                         entity_id=device_id, actor_id=actor_id)
    return True


def register_v2_device(db: DbSession, session_id: int, hello, provenance: str) -> int:
    """Upsert the device and one sensor row per declared IMU / force channel."""
    device = db.execute(select(Device).where(Device.device_id == hello.device_id)).scalar_one_or_none()
    if device is None:
        device = Device(device_id=hello.device_id)
        db.add(device)
    device.kind = (DeviceKind.HARDWARE if provenance == prov.PHYSICAL_REGISTERED
                   else DeviceKind.SIMULATOR if provenance in (prov.SIMULATED, prov.PUBLIC_DATASET_REPLAY)
                   else DeviceKind.UNVERIFIED)
    device.leg = None  # one device carries both sides
    device.firmware_version = hello.firmware_version
    device.protocol_version = hello.protocol_version
    device.status = DeviceStatus.ONLINE
    device.last_seen = _now()
    device.sample_rate_hz = hello.sample_rate_hz
    db.flush()

    declared: dict[str, tuple[SensorType, SensorLocation]] = {}
    for imu in hello.imus:
        declared[f"imu_{imu.side.value.lower()}"] = (
            SensorType.IMU, _PLACEMENT_LOCATION.get(imu.placement.value, SensorLocation.SHIN)
        )
    for ch in hello.force_channels:
        declared[f"force_{ch.id}"] = (SensorType.FSR, SensorLocation.FOOT)

    existing = {s.capability: s for s in device.sensors}
    for cap, (stype, loc) in declared.items():
        sensor = existing.get(cap)
        if sensor is None:
            sensor = Sensor(device_pk=device.id, type=stype, location=loc, capability=cap)
            db.add(sensor)
        sensor.status = SensorStatus.OK
        sensor.last_seen = _now()
    for cap, sensor in existing.items():
        if cap not in declared:
            sensor.status = SensorStatus.ABSENT

    session = db.get(SessionModel, session_id)
    if session is not None:
        from app.db.models.session import SessionMode

        session.protocol_version = 2
        session.mode = SessionMode(prov.session_mode_for(provenance))
        session.provenance = provenance
    # The recording row is created with the first stored samples (see
    # hw_registry): a handshake alone is not a recording.
    audit_service.record(
        db, action=AuditAction.DEVICE_CONNECTED, entity_type="device",
        entity_id=device.device_id, session_id=session_id, protocol=2,
        simulated=hello.simulated, provenance=provenance,
    )
    db.commit()
    return device.id


def ensure_recording(db: DbSession, session_id: int, device, hello, provenance: str):
    """One recording per session, created at the first handshake."""
    import uuid

    from app.db.models.sensing import Recording
    from app.sensing.recording import SCHEMA_VERSION, sampling_config

    rec = db.execute(select(Recording).where(Recording.session_id == session_id)).scalar_one_or_none()
    if rec is None:
        rec = Recording(recording_uid=str(uuid.uuid4()), session_id=session_id,
                        schema_version=SCHEMA_VERSION, provenance=provenance,
                        device_pk=device.id, device_id=device.device_id,
                        firmware_version=hello.firmware_version,
                        protocol_version=hello.protocol_version,
                        sampling_config=sampling_config(hello, get_settings()),
                        started_at=_now())
        db.add(rec)
    elif rec.firmware_version != hello.firmware_version:
        # Firmware changed mid-session: record it, never overwrite silently.
        rec.sampling_config = {**(rec.sampling_config or {}),
                               "firmware_changes": (rec.sampling_config or {}).get("firmware_changes", [])
                               + [{"at": _now().isoformat(), "firmware_version": hello.firmware_version}]}
    return rec


def persist_marker(db: DbSession, session_id: int, payload: dict, created_by: int | None = None):
    from app.db.models.sensing import SessionMarker

    m = SessionMarker(session_id=session_id, t_session=payload.get("t_session"),
                      server_ts=_now(), label=payload.get("label") or payload["kind"],
                      note=payload.get("note"), kind=payload["kind"], source=payload["source"],
                      time_basis=payload["time_basis"],
                      t_uncertainty_s=payload.get("t_uncertainty_s"), created_by=created_by)
    db.add(m)
    db.flush()
    return m


def finalize_recording(db: DbSession, session_id: int) -> dict | None:
    """Compute the recording's metadata and integrity from the stored samples."""
    from app.db.models.sensing import Recording
    from app.sensing.recording import build_metadata, check_integrity, scan

    rec = db.execute(select(Recording).where(Recording.session_id == session_id)).scalar_one_or_none()
    session = db.get(SessionModel, session_id)
    if rec is None or session is None:
        return None
    rec.ended_at = rec.ended_at or _now()
    result = scan(session_chunks(db, session_id), decode_chunk)
    cals = list(db.execute(select(DeviceCalibration).where(DeviceCalibration.session_id == session_id)
                           .order_by(DeviceCalibration.sequence)).scalars())
    subject = (session.research_protocol or {}).get("subject_code") or pseudonym(session.patient_id)
    meta = build_metadata(recording=rec, session=session, scan_result=result,
                          summary=session.summary, calibrations=cals, subject_code=subject,
                          consent=has_training_consent(db, session.patient_id))
    imus = (rec.sampling_config or {}).get("imus") or []
    ranges = {"acc": max([i.get("accel_range_g") or 4.0 for i in imus] or [4.0]),
              "gyro": max([i.get("gyro_range_dps") or 500.0 for i in imus] or [500.0])}
    integrity = check_integrity(result, meta, cals, ranges)
    rec.metadata_json = meta
    rec.integrity = integrity
    rec.integrity_status = integrity["status"]
    return meta


def pseudonym(patient_id: int) -> str:
    """Stable, non-reversible subject code (HMAC with the server secret)."""
    import hashlib
    import hmac

    key = get_settings().secret_key.encode()
    return "subj_" + hmac.new(key, f"patient:{patient_id}".encode(), hashlib.sha256).hexdigest()[:16]


def mark_device_offline(db: DbSession, device_id: str) -> None:
    device = db.execute(select(Device).where(Device.device_id == device_id)).scalar_one_or_none()
    if device:
        device.status = DeviceStatus.OFFLINE
        device.last_seen = _now()
        audit_service.record(db, action=AuditAction.DEVICE_DISCONNECTED, entity_type="device",
                             entity_id=device_id)
        db.commit()


def update_device_status(db: DbSession, device_pk: int, status: dict) -> None:
    device = db.get(Device, device_pk)
    if device is None:
        return
    if status.get("battery_pct") is not None:
        device.battery_level = float(status["battery_pct"])
    device.last_seen = _now()
    for side in ("left", "right"):
        ok = status.get(f"imu_{side}_ok")
        if ok is None:
            continue
        for sensor in device.sensors:
            if sensor.capability == f"imu_{side}":
                sensor.status = SensorStatus.OK if ok else SensorStatus.DEGRADED


# --------------------------------------------------------------------- #
# per-event persistence
# --------------------------------------------------------------------- #

def invalidate_calibration(db: DbSession, session_id: int, sequence: int, reason: str) -> None:
    row = db.execute(select(DeviceCalibration).where(
        DeviceCalibration.session_id == session_id, DeviceCalibration.sequence == sequence,
    )).scalar_one_or_none()
    if row is None or row.invalidated_at is not None:
        return
    row.invalidated_at = _now()
    row.invalidation_reason = reason[:200]
    audit_service.record(db, action=AuditAction.CALIBRATION_INVALIDATED, entity_type="calibration",
                         entity_id=row.id, session_id=session_id, reason=reason[:120])


def persist_calibration(db: DbSession, session_id: int, device_pk: int | None, payload: dict) -> int:
    meta = payload["metadata"]
    windows = meta.get("windows") or {}
    span = [w for w in (windows.get("still"), windows.get("movement")) if w]
    row = DeviceCalibration(
        sequence=payload.get("sequence", 1),
        t_start=span[0][0] if span else None,
        t_end=span[-1][1] if span else None,
        device_pk=device_pk,
        session_id=session_id,
        status=CalibrationOutcome(meta["status"]),
        quality=meta.get("quality"),
        sampling_rate_declared=meta["sampling_rate"]["declared_hz"],
        sampling_rate_measured=meta["sampling_rate"]["measured_hz"],
        firmware_version=payload.get("firmware_version"),
        simulated=bool(payload.get("simulated")),
        calibration_version=meta["calibration_version"],
        payload=meta,
    )
    db.add(row)
    session = db.get(SessionModel, session_id)
    if session is not None:
        from app.db.models.session import CalibrationState

        session.calibration_state = (
            CalibrationState.FAILED if meta["phase"] == "FAILED" else CalibrationState.COMPLETE
        )
        session.calibration_quality = meta.get("quality")
    db.flush()
    audit_service.record(db, action=AuditAction.CALIBRATION_RECORDED, entity_type="calibration",
                         entity_id=row.id, session_id=session_id, status=meta["status"])
    return row.id


def persist_chunk(db: DbSession, session_id: int, device_pk: int | None,
                  calibration_id: int | None, payload: dict, *, retain: bool = False) -> None:
    """Store one raw chunk.

    `retain` (research recordings from verified hardware with active consent)
    keeps the chunk out of the expiry job; everything else expires.
    """
    days = get_settings().raw_sample_retention_days
    db.add(SensorSampleChunk(
        session_id=session_id,
        device_pk=device_pk,
        chunk_index=payload["chunk_index"],
        t_start=payload["t_start"],
        t_end=payload["t_end"],
        n_samples=payload["n_samples"],
        columns=payload["columns"],
        encoding=payload["encoding"],
        data=payload["data"],
        calibration_id=calibration_id,
        simulated=bool(payload.get("simulated")),
        device_t0=payload.get("device_t0"),
        firmware_version=payload.get("firmware_version"),
        packet_log=payload.get("packet_log"),
        retain_for_training=retain,
        expires_at=None if retain else _now() + timedelta(days=days),
        created_at=_now(),
    ))


def persist_activity(db: DbSession, session_id: int, payload: dict,
                     model_version_id: int | None) -> None:
    db.add(ActivityResult(
        session_id=session_id,
        t_start=payload["t_start"], t_end=payload["t_end"],
        status=InferenceStatus(payload["status"]),
        activity=payload.get("activity"),
        candidate=payload.get("candidate"),
        confidence=payload.get("confidence"),
        probabilities=payload.get("probabilities"),
        model_ref=payload.get("model"),
        model_version_id=model_version_id,
        inference_ms=payload.get("inference_ms"),
    ))


def persist_assessment(db: DbSession, session_id: int, payload: dict,
                       kind: AssessmentKind = AssessmentKind.WINDOW) -> None:
    bil = payload.get("bilateral") or {}
    mqi = payload.get("mqi") or payload.get("movement_quality") or {}
    db.add(MovementAssessment(
        session_id=session_id, kind=kind,
        t_start=payload.get("t_start", 0.0), t_end=payload.get("t_end", 0.0),
        mqi=mqi.get("mqi"), mqi_confidence=mqi.get("confidence"),
        asymmetry_score=bil.get("asymmetry_score"),
        asymmetry_confidence=bil.get("confidence"),
        bilateral=bil or None, force_motion=payload.get("force_motion"),
        phase=payload.get("phase"), quality=mqi or None,
        pipeline_version=PIPELINE_VERSION,
    ))


def persist_rep(db: DbSession, session_id: int, payload: dict) -> None:
    exists = db.execute(select(RepetitionResult.id).where(
        RepetitionResult.session_id == session_id,
        RepetitionResult.side == payload["side"],
        RepetitionResult.rep_index == payload["rep_index"],
    )).first()
    if exists:
        return
    db.add(RepetitionResult(
        session_id=session_id, side=payload["side"], kind=payload["kind"],
        rep_index=payload["rep_index"], t_start=payload["t_start"], t_peak=payload["t_peak"],
        t_end=payload["t_end"], rom_proxy_deg=payload["rom_proxy_deg"],
        peak_velocity_dps=payload.get("peak_velocity_dps"),
        smoothness_sparc=payload.get("smoothness_sparc"),
        force_peak=payload.get("force_peak"), force_peak_lag_s=payload.get("force_peak_lag_s"),
        phase_durations=payload.get("phase_durations_s"),
        detector_version=payload["detector_version"],
    ))


def model_version_id(db: DbSession, ref: str | None) -> int | None:
    if not ref or "/" not in ref:
        return None
    name, version = ref.split("/", 1)
    row = db.execute(select(ModelVersion.id).where(
        ModelVersion.name == name, ModelVersion.version == version)).first()
    return row[0] if row else None


# --------------------------------------------------------------------- #
# baselines
# --------------------------------------------------------------------- #

def active_baseline(db: DbSession, patient_id: int, exercise_type: str) -> PatientBaseline | None:
    return db.execute(
        select(PatientBaseline).where(
            PatientBaseline.patient_id == patient_id,
            PatientBaseline.exercise_type == exercise_type,
            PatientBaseline.active.is_(True),
        ).order_by(PatientBaseline.created_at.desc())
    ).scalars().first()


def baseline_rom_for_session(db: DbSession, session_id: int) -> dict[str, float]:
    session = db.get(SessionModel, session_id)
    if session is None:
        return {}
    b = active_baseline(db, session.patient_id, session.exercise_type.value)
    if b is None:
        return {}
    return {
        side: b.metrics[f"rom_proxy_deg_{side.lower()}"]
        for side in ("LEFT", "RIGHT")
        if b.metrics.get(f"rom_proxy_deg_{side.lower()}") is not None
    }


# --------------------------------------------------------------------- #
# consent, retention and export
# --------------------------------------------------------------------- #

def has_training_consent(db: DbSession, patient_id: int) -> bool:
    row = db.execute(
        select(DataUseConsent).where(
            DataUseConsent.patient_id == patient_id,
            DataUseConsent.scope == ConsentScope.MODEL_TRAINING,
        ).order_by(DataUseConsent.created_at.desc(), DataUseConsent.id.desc())
    ).scalars().first()
    return bool(row and row.granted and row.revoked_at is None)


def set_training_retention(db: DbSession, patient_id: int, retain: bool) -> int:
    """Mark (or unmark) a patient's verified-hardware chunks as retained for training.

    Only sessions from registered, authenticated devices (mode LIVE) qualify;
    simulated and unverified recordings are never training data.
    """
    from app.db.models.session import SessionMode

    session_ids = select(SessionModel.id).where(SessionModel.patient_id == patient_id,
                                                SessionModel.mode == SessionMode.LIVE)
    result = db.execute(
        update(SensorSampleChunk)
        .where(SensorSampleChunk.session_id.in_(session_ids),
               SensorSampleChunk.simulated.is_(False))
        .values(retain_for_training=retain)
    )
    return result.rowcount or 0


def purge_expired_chunks(db: DbSession, now: datetime | None = None) -> int:
    """Retention job: delete expired raw chunks not retained for training."""
    now = now or _now()
    result = db.execute(
        delete(SensorSampleChunk).where(
            SensorSampleChunk.expires_at.is_not(None),
            SensorSampleChunk.expires_at < now,
            SensorSampleChunk.retain_for_training.is_(False),
        )
    )
    count = result.rowcount or 0
    if count:
        audit_service.record(db, action=AuditAction.RAW_SAMPLES_PURGED, entity_type="sensor_chunks",
                             count=count)
    return count


def decode_chunk(chunk: SensorSampleChunk) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(t float64, seq int64, values float32[n, C]) exactly as stored."""
    raw = zlib.decompress(chunk.data)
    n, c = chunk.n_samples, len(chunk.columns) - 2
    if chunk.encoding == "rs-raw-v2":
        t = np.frombuffer(raw, dtype="<f8", count=n)
        seq = np.frombuffer(raw, dtype="<i8", count=n, offset=8 * n)
        values = np.frombuffer(raw, dtype="<f4", offset=16 * n).reshape(n, c)
        return t, seq, values
    if chunk.encoding == "float32-le-zlib":   # legacy: everything float32
        flat = np.frombuffer(raw, dtype="<f4").reshape(n, c + 2)
        return flat[:, 0].astype(np.float64), flat[:, 1].astype(np.int64), flat[:, 2:]
    raise ValueError(f"unknown chunk encoding {chunk.encoding}")


def session_samples(db: DbSession, session_id: int) -> tuple[list[str], np.ndarray]:
    """Columns and a float64 [t, seq, values...] array (convenience view)."""
    chunks = session_chunks(db, session_id)
    if not chunks:
        return [], np.empty((0, 0))
    parts = [decode_chunk(c) for c in chunks]
    data = np.vstack([np.column_stack([t, seq.astype(np.float64), v.astype(np.float64)])
                      for t, seq, v in parts])
    return list(chunks[0].columns), data


def session_chunks(db: DbSession, session_id: int) -> list[SensorSampleChunk]:
    return list(db.execute(
        select(SensorSampleChunk).where(SensorSampleChunk.session_id == session_id)
        .order_by(SensorSampleChunk.chunk_index)
    ).scalars().all())


def summary_from_persisted(db: DbSession, session: SessionModel) -> dict:
    """Rebuild a minimal v2 summary when the live processor is gone.

    Happens if the server restarted mid-session. Only what was persisted can
    be reported: repetition rows and the latest window assessment. It says so.
    """
    reps = db.execute(select(RepetitionResult).where(
        RepetitionResult.session_id == session.id)).scalars().all()
    last = db.execute(select(MovementAssessment).where(
        MovementAssessment.session_id == session.id).order_by(
        MovementAssessment.t_end.desc())).scalars().first()
    by_side: dict = {}
    for side in ("LEFT", "RIGHT"):
        rs = [r for r in reps if r.side == side]
        if rs:
            by_side[side] = {
                "count": len(rs),
                "rom_proxy_deg_mean": round(float(np.mean([r.rom_proxy_deg for r in rs])), 2),
                "peak_velocity_dps_mean": round(float(np.mean(
                    [r.peak_velocity_dps for r in rs if r.peak_velocity_dps is not None] or [0])), 1),
                "duration_s_mean": round(float(np.mean([r.t_end - r.t_start for r in rs])), 3),
            }
    return {
        "analytics_version": PIPELINE_VERSION,
        "protocol_version": 2,
        "rebuilt_from_persisted": True,
        "duration_s": None if last is None else round(last.t_end, 2),
        "exercise_type": session.exercise_type.value,
        "session_mode": session.mode.value,
        "repetitions": len(reps),
        "repetition_summary": by_side,
        "bilateral": None if last is None else last.bilateral,
        "force_motion": None if last is None else last.force_motion,
        "movement_quality": None if last is None else last.quality,
        "confidence": None,
        "data_quality": {},
        "rom_deg": None, "symmetry_index_pct": None, "recovery_score": None,
        "validation": {"rehabsense_hardware": "NOT_VALIDATED", "clinical": "NOT_VALIDATED"},
        "disclaimer": "Rebuilt from persisted rows after the live processor was lost; "
                      "session-level figures are partial.",
    }


def research_retention(db: DbSession, session_id: int) -> bool:
    """Raw chunks of this session are kept for training iff: research mode,
    verified hardware (mode LIVE) and active MODEL_TRAINING consent."""
    from app.db.models.session import RecordingMode, SessionMode

    s = db.get(SessionModel, session_id)
    return bool(s and s.recording_mode is RecordingMode.RESEARCH and s.mode is SessionMode.LIVE
                and has_training_consent(db, s.patient_id))
