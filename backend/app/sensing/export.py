"""Reproducible research export of one recording.

    <out>/
      manifest.json            schema version, recording id, files, sample counts, SHA-256
      metadata.json            recording metadata (provenance, sampling, availability, clock, ...)
      samples.npz              RAW: exactly the stored samples + per-packet receive log
      events.json              markers (source + time basis for each)
      labels.json              HUMAN labels only, with tier (GOLD / SILVER)
      predictions.json         MODEL outputs only (activity + confidence, detected repetitions)
      calibration.json         every calibration of the session, incl. superseded ones
      integrity.json           integrity checks recomputed from samples.npz
      derived/calibrated.npz   DERIVED: raw values with the valid calibration applied

`samples.npz` is the one sample format used everywhere (the training export
and finetune_rehabsense.py read it too). RAW and DERIVED are separate files;
nothing in RAW is interpolated, filled or repaired: an unavailable sensor is
NaN, a lost sample is a gap in `seq`.

`deidentify=True` (training export) drops free-text notes and operator notes;
subjects are only ever identified by a pseudonymous code.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models.base import utc_iso
from app.db.models.sensing import (
    ActivityResult,
    DeviceCalibration,
    Recording,
    RepetitionResult,
    SessionLabel,
    SessionMarker,
)
from app.db.models.session import Session as SessionModel
from app.sensing.recording import SCHEMA_VERSION, check_integrity, scan

EXPORT_VERSION = "rs-export-1.0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def label_tier_summary(labels: list) -> str:
    """GOLD if any label is second-rater confirmed, SILVER if any human label,
    else UNLABELED. MODEL-GENERATED outputs never count here."""
    if any(l.tier == "GOLD" for l in labels):
        return "GOLD"
    if labels:
        return "SILVER"
    return "UNLABELED"


def export_recording(db: DbSession, session_id: int, out: Path, *, deidentify: bool = False) -> dict:
    from app.services import sensing_service

    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)          # never overwrite an export
    (out / "derived").mkdir()
    session = db.get(SessionModel, session_id)
    rec = db.execute(select(Recording).where(Recording.session_id == session_id)).scalar_one_or_none()
    if session is None or rec is None:
        raise ValueError("no protocol-v2 recording for this session")
    if rec.metadata_json is None:
        sensing_service.finalize_recording(db, session_id)
    meta = dict(rec.metadata_json)
    if deidentify:
        rp = dict(meta.get("research_protocol") or {})
        rp.pop("operator_notes", None)
        meta["research_protocol"] = rp or None

    chunks = sensing_service.session_chunks(db, session_id)
    result = scan(chunks, sensing_service.decode_chunk)
    names = result.get("names") or []
    t0s = {c.device_t0 for c in chunks if c.device_t0 is not None}
    device_t0 = next(iter(t0s)) if len(t0s) == 1 else None
    packets = result.get("packets") or []
    pk = np.asarray([[p[0], p[1], p[2], np.nan if p[3] is None else p[3]] for p in packets],
                    dtype=np.float64).reshape(-1, 4)
    n = result.get("samples", 0)
    np.savez_compressed(
        out / "samples.npz",
        t=result["t"] if n else np.empty(0), seq=result["seq"] if n else np.empty(0, np.int64),
        device_ts=(result["t"] + device_t0) if n and device_t0 is not None else np.empty(0),
        values=result["values"] if n else np.empty((0, len(names)), np.float32),
        columns=np.array(names),
        packet_first_seq=pk[:, 0].astype(np.int64), packet_n=pk[:, 1].astype(np.int64),
        packet_server_receive_unix=pk[:, 2], packet_device_sent_ts=pk[:, 3],
    )

    markers = db.execute(select(SessionMarker).where(SessionMarker.session_id == session_id)
                         .order_by(SessionMarker.server_ts)).scalars().all()
    _write_json(out / "events.json", {
        "time_bases": {"DEVICE_TIME": "stamped on (or derived from) device sample time",
                       "SERVER_RECEIVE_TIME_MAPPED": "server/user instant mapped onto device "
                                                     "time; see t_uncertainty_s"},
        "events": [{"kind": m.kind, "label": m.label, "source": m.source,
                    "time_basis": m.time_basis, "t_session": m.t_session,
                    "t_uncertainty_s": m.t_uncertainty_s, "server_ts": utc_iso(m.server_ts),
                    **({} if deidentify else {"note": m.note})} for m in markers],
    })

    labels = db.execute(select(SessionLabel).where(SessionLabel.session_id == session_id)
                        .order_by(SessionLabel.t_start)).scalars().all()
    _write_json(out / "labels.json", {
        "kind": "HUMAN_LABEL",
        "recording_label_tier": label_tier_summary(labels),
        "tiers": {"GOLD": "confirmed by a second, different human",
                  "SILVER": "one human", "UNLABELED": "no human label"},
        "labels": [{"t_start": l.t_start, "t_end": l.t_end, "tier": l.tier, "source": l.source,
                    "exercise_type": l.exercise_type, "activity": l.activity,
                    "repetition_index": l.repetition_index, "side": l.side,
                    "movement_phase": l.movement_phase, "quality_rating": l.quality_rating,
                    "labeller": None if deidentify else l.labeller_id,
                    "confirmed": l.confirmed_by is not None,
                    **({} if deidentify else {"notes": l.notes})} for l in labels],
    })

    acts = db.execute(select(ActivityResult).where(ActivityResult.session_id == session_id)
                      .order_by(ActivityResult.t_start)).scalars().all()
    reps = db.execute(select(RepetitionResult).where(RepetitionResult.session_id == session_id)
                      .order_by(RepetitionResult.t_start)).scalars().all()
    _write_json(out / "predictions.json", {
        "kind": "MODEL_PREDICTION",
        "warning": "Model outputs. Never human labels; never used as ground truth.",
        "activity": [{"t_start": a.t_start, "t_end": a.t_end, "status": a.status.value,
                      "prediction": a.activity, "candidate": a.candidate,
                      "confidence": a.confidence, "model": a.model_ref} for a in acts],
        "repetitions_detected": [{"side": r.side, "rep_index": r.rep_index, "t_start": r.t_start,
                                  "t_peak": r.t_peak, "t_end": r.t_end,
                                  "rom_proxy_deg": r.rom_proxy_deg, "detector": r.detector_version}
                                 for r in reps],
    })

    cals = db.execute(select(DeviceCalibration).where(DeviceCalibration.session_id == session_id)
                      .order_by(DeviceCalibration.sequence)).scalars().all()
    _write_json(out / "calibration.json", {"calibrations": [{
        "calibration_id": c.id, "sequence": c.sequence, "status": c.status.value,
        "valid": c.invalidated_at is None, "invalidation_reason": c.invalidation_reason,
        "created_at": utc_iso(c.created_at), "t_start": c.t_start, "t_end": c.t_end,
        "metadata": c.payload} for c in cals]})

    imus = (rec.sampling_config or {}).get("imus") or []
    ranges = {"acc": max([i.get("accel_range_g") or 4.0 for i in imus] or [4.0]),
              "gyro": max([i.get("gyro_range_dps") or 500.0 for i in imus] or [500.0])}
    integrity = check_integrity(result, meta, cals, ranges)
    _write_json(out / "integrity.json", integrity)
    meta["integrity_status"] = integrity["status"]
    meta["human_label_tier"] = label_tier_summary(labels)
    _write_json(out / "metadata.json", meta)

    valid = [c for c in cals if c.invalidated_at is None and c.status.value in ("PASS", "WARN")]
    if valid and n:
        cm = valid[-1].payload
        v = result["values"].astype(np.float64).copy()
        for side, off in (("left", cm["left_imu_offset"]), ("right", cm["right_imu_offset"])):
            i = names.index(f"{side}_ax")
            if off.get("usable"):
                v[:, i:i + 3] *= off["accel_scale"]
                v[:, i + 3:i + 6] -= np.asarray(off["gyro_bias_dps"])
        for fid, f in (cm.get("force_offset") or {}).items():
            col = next((j for j, nm in enumerate(names) if nm.startswith(f"force_{fid}_")), None)
            if col is not None and f.get("offset") is not None:
                v[:, col] = np.maximum(0.0, v[:, col] - f["offset"])
        np.savez_compressed(out / "derived" / "calibrated.npz", t=result["t"], seq=result["seq"],
                            values=v.astype(np.float32), columns=np.array(names),
                            calibration_id=np.array(valid[-1].id),
                            note=np.array("DERIVED: raw values with bias/scale/offset of the valid "
                                          "calibration applied; see calibration.json"))

    files = sorted(p for p in out.rglob("*") if p.is_file())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "export_version": EXPORT_VERSION,
        "recording_id": rec.recording_uid,
        "provenance": rec.provenance,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "deidentified": deidentify,
        "sample_counts": {"samples.npz": n,
                          "derived/calibrated.npz": n if (out / "derived" / "calibrated.npz").exists() else 0,
                          "events.json": len(markers), "labels.json": len(labels),
                          "predictions.json": len(acts) + len(reps)},
        "files": [{"name": str(p.relative_to(out)), "bytes": p.stat().st_size,
                   "sha256": _sha256(p), "kind": "DERIVED" if "derived" in p.parts else "RAW"
                   if p.name == "samples.npz" else "METADATA"} for p in files],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def verify_export(path: Path) -> dict:
    """Recompute hashes, re-check schema and integrity of an export directory."""
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text())
    problems = []
    for f in manifest["files"]:
        p = path / f["name"]
        if not p.exists():
            problems.append(f"missing {f['name']}")
        elif _sha256(p) != f["sha256"]:
            problems.append(f"hash mismatch {f['name']}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema {manifest.get('schema_version')} != {SCHEMA_VERSION}")
    z = np.load(path / "samples.npz", allow_pickle=False)
    if len(z["t"]) != manifest["sample_counts"]["samples.npz"]:
        problems.append("sample count mismatch")
    if len(z["t"]) > 1 and (np.diff(z["seq"]) <= 0).any():
        problems.append("non-increasing seq in samples.npz")
    return {"ok": not problems, "problems": problems, "recording_id": manifest["recording_id"]}


def zip_export(directory: Path) -> bytes:
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(Path(directory).rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(directory).as_posix())
    return buf.getvalue()


def store_export(db: DbSession, session_id: int, *, deidentify: bool, actor_id: int | None):
    """Build an export, zip it, put it in object storage and record it.

    Returns (zip_bytes, artifact). The temporary build directory is only a
    staging area; the durable copy is the stored object + its DB row.
    """
    import tempfile

    from app.db.models.sensing import RecordingArtifact
    from app.services.storage import get_storage

    rec = db.execute(select(Recording).where(Recording.session_id == session_id)).scalar_one_or_none()
    if rec is None:
        raise ValueError("no protocol-v2 recording for this session")
    with tempfile.TemporaryDirectory() as tmp:
        manifest = export_recording(db, session_id, Path(tmp) / "recording", deidentify=deidentify)
        data = zip_export(Path(tmp) / "recording")
        zpath = Path(tmp) / "export.zip"
        zpath.write_bytes(data)
        stamp = manifest["created_at"].replace(":", "").replace("-", "")
        key = f"recordings/{rec.recording_uid}/export-{EXPORT_VERSION}-{stamp}{'-deid' if deidentify else ''}.zip"
        stored = get_storage().put_file(key, zpath)
    art = RecordingArtifact(recording_id=rec.id, kind="EXPORT_ZIP", storage_uri=stored.uri,
                            sha256=stored.sha256, size_bytes=stored.size_bytes,
                            schema_version=SCHEMA_VERSION, export_version=EXPORT_VERSION,
                            deidentified=deidentify, created_by=actor_id)
    db.add(art)
    db.flush()
    return data, art


def archive_raw(db: DbSession, session_id: int, actor_id: int | None = None):
    """Copy the raw samples of a completed recording to object storage (RAW_ARCHIVE)."""
    import tempfile

    from app.db.models.sensing import RecordingArtifact
    from app.services import sensing_service
    from app.services.storage import get_storage

    rec = db.execute(select(Recording).where(Recording.session_id == session_id)).scalar_one_or_none()
    if rec is None:
        raise ValueError("no protocol-v2 recording for this session")
    result = scan(sensing_service.session_chunks(db, session_id), sensing_service.decode_chunk)
    if not result.get("samples"):
        raise ValueError("recording has no stored samples")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "samples.npz"
        np.savez_compressed(p, t=result["t"], seq=result["seq"], values=result["values"],
                            columns=np.array(result["names"]))
        stored = get_storage().put_file(f"recordings/{rec.recording_uid}/raw-{SCHEMA_VERSION}.npz", p)
    art = RecordingArtifact(recording_id=rec.id, kind="RAW_ARCHIVE", storage_uri=stored.uri,
                            sha256=stored.sha256, size_bytes=stored.size_bytes,
                            schema_version=SCHEMA_VERSION, created_by=actor_id)
    db.add(art)
    db.flush()
    return art
