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


# --------------------------------------------------------------------- #
# hardware-v2 movement progress report
# --------------------------------------------------------------------- #

MOVEMENT_REPORT_VERSION = "movement-1.0"


def build_movement_report(db: DbSession, patient, *, include_clinical: bool) -> dict:
    """The longitudinal movement report, frozen from stored session data.

    Every figure comes from `movement_analytics` (itself a read of what the
    pipeline stored), so the report, the dashboard and the PDF agree.
    """
    from app.services import movement_analytics as ma

    mv = ma.patient_movement(db, patient)
    sm = mv["summary"]
    provenance = sm.get("provenance") or patient.provenance
    labels = ma.labels_for(provenance)
    disclaimers = [d for d in (labels["provenance"], ma.PROTOTYPE_NOTICE, ma.RESEARCH_LABEL,
                               "Not a medical record. Not for diagnosis or treatment decisions.") if d]
    sessions = [{
        "id": r["id"], "started_at": r["started_at"], "exercise_type": r["exercise_type"],
        "duration_s": r["duration_s"], "repetitions": r["repetitions"], "mqi": r["mqi"],
        "asymmetry_pct": r["asymmetry_pct"], "confidence_pct": r["confidence_pct"],
        "calibration_status": r["calibration_status"], "activity_top": r["activity_top"],
        "model": r["model"], "provenance": r["provenance"], "programme_day": r["programme_day"],
    } for r in mv["sessions"]]
    report = {
        "type": "MOVEMENT_PROGRESS",
        "report_version": MOVEMENT_REPORT_VERSION,
        "title": "Movement progress report",
        "generated_at": utc_iso(datetime.now(timezone.utc)),
        "patient": {"id": patient.id, "name": patient.name, "program": patient.program,
                    "operated_leg": patient.operated_leg.value, "age": patient.age},
        "provenance": provenance,
        "labels": labels,
        "disclaimers": disclaimers,
        "period": {"start": sm["start_date"], "end": (sessions[-1]["started_at"] if sessions else None),
                   "first_session": sessions[0]["started_at"] if sessions else None,
                   "days": sm["duration_days"], "programme_days": sm["programme_days"]},
        "summary": sm,
        "sessions": sessions,
        "activity_distribution": sm["activity_seconds"],
        "models": sm["models"],
        "status_rule": mv["status_rule"],
        "definitions": {
            "mqi": ("Movement Quality Index (mqi-proto-v1): equal-weight mean of symmetry, temporal "
                    "consistency, smoothness (SPARC), force consistency and repetition consistency. "
                    "Research metric, not clinically validated."),
            "asymmetry": ("Bilateral asymmetry score x 100: 0 = left and right move alike. From the "
                          "two shank IMUs; segment tilt, not a joint angle."),
            "activity": ("Activity model output (public-dataset trained). On synthetic or replayed "
                         "signals it is a model result, not an observation."),
        },
        "validation": {"rehabsense_hardware": "NOT_VALIDATED", "clinical": "NOT_VALIDATED"},
        "responsible_use": RESPONSIBLE_USE,
    }
    if include_clinical:
        from sqlalchemy import select as _select

        from app.db.models.session import Session as _Session

        first_gen = db.execute(_select(_Session.generation).where(
            _Session.patient_id == patient.id, _Session.generation.is_not(None)).limit(1)).scalar()
        report["clinical"] = {
            "notes": patient.notes,
            "generation": None if not first_gen else {
                k: first_gen.get(k) for k in ("generator", "synthetic_generator_version", "seed",
                                              "source_dataset", "model_version", "pipeline_version",
                                              "trajectory", "generation_timestamp")},
        }
    return report


def ensure_movement_report(db: DbSession, patient, *, actor, idempotency_key: str):
    """Create and generate a movement report once per key (used by the seed)."""
    from sqlalchemy import select as _select

    from app.db.models.audit import AuditAction
    from app.db.models.report import Report, ReportKind, ReportStatus
    from app.services import audit_service

    report = db.execute(_select(Report).where(Report.idempotency_key == idempotency_key)).scalar_one_or_none()
    if report is not None and report.status is ReportStatus.READY:
        return report
    if report is None:
        report = Report(patient_id=patient.id, kind=ReportKind.MOVEMENT_PROGRESS,
                        status=ReportStatus.DRAFT, idempotency_key=idempotency_key)
        db.add(report)
        db.flush()
    generate_movement_report(db, report, patient, actor_id=actor.id if actor else None)
    audit_service.record(db, action=AuditAction.REPORT_GENERATED, entity_type="report",
                         entity_id=report.id, actor_id=actor.id if actor else None,
                         patient_id=patient.id, kind=report.kind.value)
    return report


def generate_movement_report(db: DbSession, report, patient, *, actor_id: int | None) -> None:
    from app.db.models.report import ReportStatus
    from app.sensing.processor import PIPELINE_VERSION

    report.payload_patient = build_movement_report(db, patient, include_clinical=False)
    report.payload_clinician = build_movement_report(db, patient, include_clinical=True)
    report.analytics_version = PIPELINE_VERSION
    report.report_version = MOVEMENT_REPORT_VERSION
    report.status = ReportStatus.READY
    report.generated_at = datetime.now(timezone.utc)
    report.generated_by = actor_id
    db.flush()
