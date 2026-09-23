"""Report and replay construction.

Every figure here is read from persisted session data. Reports are snapshots:
once generated, the payload is frozen alongside the analytics version that
produced it, so the dashboard, the receipt and the exported file can never
disagree with each other.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.db.models.session import (
    MetricSnapshot,
    RepEvent,
    RiskFlag,
    Session as SessionModel,
)
from app.processing.recovery import compute_recovery
from app.processing.symmetry import compute_symmetry
from app.schemas.common import RESPONSIBLE_USE
from app.db.models.base import utc_iso


def summary_from_persisted(db: DbSession, session: SessionModel) -> dict:
    """Rebuild a summary from stored rows.

    Used when a session is ended without a live processor in memory (for
    example after a server restart) so the numbers still come from real
    recorded data rather than being invented.
    """
    reps = list(db.execute(select(RepEvent).where(RepEvent.session_id == session.id)).scalars())
    snapshots = list(
        db.execute(
            select(MetricSnapshot).where(MetricSnapshot.session_id == session.id)
            .order_by(MetricSnapshot.ts)
        ).scalars()
    )

    left = [r.rom_deg for r in reps if r.leg.value == "LEFT"]
    right = [r.rom_deg for r in reps if r.leg.value == "RIGHT"]
    symmetry = compute_symmetry(left, right, session.patient.operated_leg if session.patient else None)

    rom = max((s.rom_running_deg or 0.0 for s in snapshots), default=None)
    cadence = next((s.cadence_spm for s in reversed(snapshots) if s.cadence_spm), None)
    recovery = compute_recovery(
        rom_deg=rom, lsi_pct=symmetry.lsi_pct, cadence_spm=cadence,
        compliance_ratio=None, reported_pain=session.reported_pain,
    )
    last_conf = next((s.recovery_confidence for s in reversed(snapshots) if s.recovery_confidence), None)

    return {
        "analytics_version": get_settings().analytics_version,
        "duration_s": session.duration_seconds,
        "exercise_type": session.exercise_type.value,
        "session_mode": session.mode.value,
        "rom_deg": rom,
        "cadence_spm": cadence,
        "symmetry": symmetry.as_dict(),
        "symmetry_index_pct": symmetry.lsi_pct,
        "recovery": recovery.as_dict(),
        "recovery_score": None if recovery.score is None else round(recovery.score, 1),
        "repetitions": len(reps),
        "repetitions_left": len(left),
        "repetitions_right": len(right),
        "mean_rep_quality": (
            round(sum(r.quality_score or 0 for r in reps) / len(reps), 3) if reps else None
        ),
        "confidence": session.confidence or (
            {"value": last_conf, "percent": None if last_conf is None else round(last_conf * 100, 1)}
        ),
        "data_quality": session.data_quality or {},
        "reconstructed": True,
        "disclaimer": RESPONSIBLE_USE,
    }


def build_session_report(db: DbSession, session: SessionModel, *, include_clinical: bool) -> dict:
    """The authoritative session report.

    `include_clinical` gates the clinician-only sections at the *server*; the
    patient payload simply does not contain them.
    """
    summary = session.summary or summary_from_persisted(db, session)
    reps = list(
        db.execute(
            select(RepEvent).where(RepEvent.session_id == session.id).order_by(RepEvent.rep_index)
        ).scalars()
    )
    risks = list(
        db.execute(select(RiskFlag).where(RiskFlag.session_id == session.id).order_by(RiskFlag.ts)).scalars()
    )

    report = {
        "session": {
            "id": session.id,
            "exercise_type": session.exercise_type.value,
            "status": session.status.value,
            "mode": session.mode.value,
            "started_at": utc_iso(session.started_at),
            "ended_at": utc_iso(session.ended_at),
            "duration_s": session.duration_seconds,
            "reported_pain": session.reported_pain,
        },
        "patient": {
            "id": session.patient.id,
            "name": session.patient.name,
            "operated_leg": session.patient.operated_leg.value,
        } if session.patient else None,
        "metrics": {
            "rom_deg": summary.get("rom_deg"),
            "cadence_spm": summary.get("cadence_spm"),
            "symmetry_index_pct": summary.get("symmetry_index_pct"),
            "recovery_score": summary.get("recovery_score"),
            "repetitions": summary.get("repetitions"),
            "mean_rep_quality": summary.get("mean_rep_quality"),
        },
        "recovery": summary.get("recovery"),
        "symmetry": summary.get("symmetry"),
        "confidence": summary.get("confidence"),
        "repetitions": [
            {
                "rep_index": r.rep_index, "leg": r.leg.value, "rom_deg": r.rom_deg,
                "duration_s": r.duration_s, "quality_score": r.quality_score,
                "t_offset": r.t_offset,
            }
            for r in reps
        ],
        "risk_flags": [
            {"severity": f.severity.value, "message": f.message, "t_offset": f.t_offset,
             "acknowledged": f.acknowledged}
            for f in risks
        ],
        "analytics_version": summary.get("analytics_version"),
        "responsible_use": RESPONSIBLE_USE,
    }

    if include_clinical:
        report["clinical"] = {
            "data_quality": summary.get("data_quality"),
            "calibration_state": session.calibration_state.value,
            "notes": session.notes,
            "patient_notes": session.patient.notes if session.patient else None,
        }
    return report


def build_replay(db: DbSession, session: SessionModel) -> dict:
    """Compact replay track: one frame per stored snapshot, plus events."""
    snapshots = list(
        db.execute(
            select(MetricSnapshot).where(MetricSnapshot.session_id == session.id)
            .order_by(MetricSnapshot.t_offset)
        ).scalars()
    )
    reps = list(
        db.execute(
            select(RepEvent).where(RepEvent.session_id == session.id).order_by(RepEvent.t_offset)
        ).scalars()
    )
    risks = list(
        db.execute(
            select(RiskFlag).where(RiskFlag.session_id == session.id).order_by(RiskFlag.t_offset)
        ).scalars()
    )

    return {
        "session_id": session.id,
        "duration_s": session.duration_seconds
        or (snapshots[-1].t_offset if snapshots else 0.0),
        "exercise_type": session.exercise_type.value,
        "sample_interval_s": 1.0,
        "frames": [
            {
                "t": round(s.t_offset, 2),
                "left_knee_angle_deg": s.left_knee_angle_deg,
                "right_knee_angle_deg": s.right_knee_angle_deg,
                "rom_running_deg": s.rom_running_deg,
                "cadence_spm": s.cadence_spm,
                "symmetry_index_pct": s.symmetry_index_pct,
                "recovery_score": s.recovery_score,
                "confidence": s.recovery_confidence,
            }
            for s in snapshots
        ],
        "repetitions": [
            {"t": round(r.t_offset, 2), "leg": r.leg.value, "rep_index": r.rep_index,
             "rom_deg": r.rom_deg, "quality_score": r.quality_score}
            for r in reps
        ],
        "events": [
            {"t": round(f.t_offset, 2), "severity": f.severity.value, "message": f.message}
            for f in risks
        ],
        "responsible_use": RESPONSIBLE_USE,
    }
