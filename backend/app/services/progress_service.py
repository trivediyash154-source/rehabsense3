"""Longitudinal progress, comparison and trends.

The frontend never recomputes any of this: baseline/current deltas, trend
slopes and milestone detection all originate here so every surface agrees.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.core.exceptions import InsufficientData
from app.db.models.patient import PatientProfile
from app.db.models.session import RepEvent, Session as SessionModel, SessionStatus
from app.schemas.common import RESPONSIBLE_USE
from app.db.models.base import utc_iso

TRACKED = [
    ("rom_deg", "Knee ROM estimate", "°"),
    ("symmetry_index_pct", "Bilateral symmetry", "%"),
    ("cadence_spm", "Cadence estimate", "steps/min"),
    ("recovery_score", "Recovery indicator", "/100"),
]


def completed_sessions(
    db: DbSession, patient_id: int, *, start: date | None = None, end: date | None = None
) -> list[SessionModel]:
    stmt = (
        select(SessionModel)
        .where(SessionModel.patient_id == patient_id, SessionModel.status == SessionStatus.COMPLETED)
        .order_by(SessionModel.started_at)
    )
    if start:
        stmt = stmt.where(SessionModel.started_at >= datetime.combine(start, datetime.min.time()))
    if end:
        stmt = stmt.where(SessionModel.started_at <= datetime.combine(end, datetime.max.time()))
    return list(db.execute(stmt).scalars())


def _metric(session: SessionModel, key: str):
    summary = session.summary or {}
    return summary.get(key)


def _linear_trend(values: list[float]) -> dict:
    """Least-squares slope over the session index.

    Deliberately a simple linear fit, as specified for the MVP; the shape of
    this function is what a segmented fit would later replace.
    """
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(points) < 2:
        return {"slope": None, "direction": "insufficient", "n": len(points)}
    n = len(points)
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    denom = sum((p[0] - mean_x) ** 2 for p in points)
    if denom == 0:
        return {"slope": None, "direction": "flat", "n": n}
    slope = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / denom
    direction = "improving" if slope > 0.5 else "declining" if slope < -0.5 else "flat"
    return {"slope": round(slope, 3), "direction": direction, "n": n,
            "intercept": round(mean_y - slope * mean_x, 3)}


def session_brief(session: SessionModel) -> dict:
    summary = session.summary or {}
    confidence = session.confidence or {}
    return {
        "id": session.id,
        "started_at": utc_iso(session.started_at),
        "day_label": session.started_at.strftime("%d %b") if session.started_at else None,
        "exercise_type": session.exercise_type.value,
        "duration_s": session.duration_seconds,
        "rom_deg": summary.get("rom_deg"),
        "symmetry_index_pct": summary.get("symmetry_index_pct"),
        "cadence_spm": summary.get("cadence_spm"),
        "recovery_score": summary.get("recovery_score"),
        "repetitions": summary.get("repetitions"),
        "confidence": confidence.get("percent"),
        "confidence_band": confidence.get("band"),
        # Share of the session with both limbs reporting. Carried on the brief
        # so a list view does not have to fetch every session's detail -- and
        # so the frontend never has to approximate it from something else.
        "coverage_pct": (
            round(confidence["bilateral_coverage"] * 100, 1)
            if confidence.get("bilateral_coverage") is not None
            else None
        ),
        "peak_angle_left_deg": summary.get("peak_angle_left_deg"),
        "peak_angle_right_deg": summary.get("peak_angle_right_deg"),
        "mode": session.mode.value,
    }


def build_progress(db: DbSession, patient: PatientProfile, *, start=None, end=None) -> dict:
    sessions = completed_sessions(db, patient.id, start=start, end=end)
    if not sessions:
        return {
            "patient_id": patient.id,
            "session_count": 0,
            "sessions": [],
            "baseline": None,
            "latest": None,
            "trends": {},
            "milestones": [],
            "responsible_use": RESPONSIBLE_USE,
        }

    briefs = [session_brief(s) for s in sessions]
    trends = {
        key: _linear_trend([b[key] for b in briefs])
        for key, _label, _unit in TRACKED
    }

    return {
        "patient_id": patient.id,
        "operated_leg": patient.operated_leg.value,
        "session_count": len(sessions),
        "period_days": (
            (sessions[-1].started_at - sessions[0].started_at).days if len(sessions) > 1 else 0
        ),
        "sessions": briefs,
        "baseline": briefs[0],
        "latest": briefs[-1],
        "trends": trends,
        "milestones": _milestones(sessions, briefs),
        "total_repetitions": sum(b["repetitions"] or 0 for b in briefs),
        "analytics_version": get_settings().analytics_version,
        "responsible_use": RESPONSIBLE_USE,
    }


def _milestones(sessions: list[SessionModel], briefs: list[dict]) -> list[dict]:
    """Progress events derived from the data. Never framed as achievements."""
    out: list[dict] = []
    if not sessions:
        return out

    out.append({
        "kind": "start", "session_id": sessions[0].id, "title": "Baseline recorded",
        "detail": "First completed session; every later comparison is made against it.",
    })

    best = max((b for b in briefs if b["rom_deg"] is not None), key=lambda b: b["rom_deg"], default=None)
    if best and len(briefs) > 1:
        out.append({
            "kind": "range", "session_id": best["id"], "title": "Highest recorded range",
            "detail": f"Estimated peak ROM of {best['rom_deg']:.0f}° — the largest in this period.",
        })

    for b in briefs:
        if b["confidence"] is not None and b["confidence"] < 55:
            out.append({
                "kind": "trend", "session_id": b["id"], "title": "Reduced signal confidence",
                "detail": f"Confidence {b['confidence']:.0f}% — interpret this session with more caution.",
            })
            break

    if len(briefs) > 1:
        out.append({
            "kind": "latest", "session_id": briefs[-1]["id"], "title": "Most recent session",
            "detail": f"{briefs[-1]['exercise_type'].replace('_', ' ').title()} on {briefs[-1]['day_label']}.",
        })
    return out


def compare(
    db: DbSession, patient: PatientProfile,
    *, baseline_session_id: int | None = None, current_session_id: int | None = None,
    start=None, end=None,
) -> dict:
    """Authoritative old-vs-new comparison."""
    sessions = completed_sessions(db, patient.id, start=start, end=end)
    if len(sessions) < 1:
        raise InsufficientData("No completed sessions to compare.")

    by_id = {s.id: s for s in sessions}
    baseline = by_id.get(baseline_session_id) if baseline_session_id else sessions[0]
    current = by_id.get(current_session_id) if current_session_id else sessions[-1]
    if baseline is None or current is None:
        raise InsufficientData("The requested sessions are not both completed for this patient.")

    b_brief, c_brief = session_brief(baseline), session_brief(current)

    deltas = {}
    for key, label, unit in TRACKED:
        a, b = b_brief.get(key), c_brief.get(key)
        if a is None or b is None:
            deltas[key] = {"label": label, "unit": unit, "from": a, "to": b,
                           "change": None, "direction": "unknown"}
            continue
        change = round(b - a, 1)
        deltas[key] = {
            "label": label, "unit": unit, "from": a, "to": b, "change": change,
            "direction": "up" if change > 0 else "down" if change < 0 else "flat",
        }

    elapsed_days = 0
    if baseline.started_at and current.started_at:
        elapsed_days = (current.started_at - baseline.started_at).days

    return {
        "patient_id": patient.id,
        "baseline": b_brief,
        "current": c_brief,
        "deltas": deltas,
        "trends": {k: _linear_trend([session_brief(s)[k] for s in sessions]) for k, _l, _u in TRACKED},
        "confidence": current.confidence,
        "session_count": len(sessions),
        "elapsed_days": elapsed_days,
        "summary": _summarise(deltas, current),
        "analytics_version": get_settings().analytics_version,
        "responsible_use": RESPONSIBLE_USE,
    }


def _summarise(deltas: dict, current: SessionModel) -> list[str]:
    """Plain-language 'what changed', derived from the deltas themselves."""
    lines: list[str] = []
    for key in ("rom_deg", "symmetry_index_pct", "cadence_spm"):
        d = deltas.get(key) or {}
        if d.get("change"):
            verb = "increased" if d["change"] > 0 else "decreased"
            unit = "" if d["unit"] == "/100" else d["unit"]
            lines.append(f"{d['label']} {verb} by {abs(d['change'])}{unit}.")
    summary = current.summary or {}
    if summary.get("repetitions"):
        lines.append(f"The later session recorded {summary['repetitions']} repetitions.")
    confidence = current.confidence or {}
    if confidence.get("explanation"):
        lines.append(confidence["explanation"])
    return lines


def build_passport(db: DbSession, patient: PatientProfile) -> dict:
    """Cumulative record across the whole period."""
    progress = build_progress(db, patient)
    reps_total = db.execute(
        select(RepEvent).join(SessionModel).where(SessionModel.patient_id == patient.id)
    ).scalars().all()

    return {
        "patient": {
            "id": patient.id,
            "name": patient.name,
            "operated_leg": patient.operated_leg.value,
            "surgery_date": patient.surgery_date.isoformat() if patient.surgery_date else None,
        },
        "session_count": progress["session_count"],
        "period_days": progress.get("period_days", 0),
        "total_repetitions": len(reps_total),
        "baseline": progress["baseline"],
        "latest": progress["latest"],
        "trends": progress["trends"],
        "milestones": progress["milestones"],
        "fingerprint": _fingerprint(progress["latest"]) if progress["latest"] else None,
        "fingerprint_baseline": _fingerprint(progress["baseline"]) if progress["baseline"] else None,
        "analytics_version": get_settings().analytics_version,
        "responsible_use": RESPONSIBLE_USE,
    }


def _fingerprint(brief: dict) -> list[dict]:
    """Six normalised axes describing the character of a session."""
    settings = get_settings()

    def pct(value, reference):
        if value is None:
            return None
        return round(min(100.0, max(0.0, value / reference * 100)), 1)

    return [
        {"axis": "Range", "value": pct(brief.get("rom_deg"), settings.target_rom_deg)},
        {"axis": "Symmetry", "value": brief.get("symmetry_index_pct")},
        {"axis": "Cadence", "value": pct(brief.get("cadence_spm"), settings.reference_cadence_spm)},
        {"axis": "Volume", "value": pct(brief.get("repetitions"), 30)},
        {"axis": "Coverage", "value": brief.get("confidence")},
        {"axis": "Consistency", "value": brief.get("recovery_score")},
    ]


def build_roster(db: DbSession, patients: list[PatientProfile]) -> list[dict]:
    """A compact movement summary per patient, for the clinician landscape.

    Built here rather than in the client so the roster's scores are the same
    stored values every other view uses, and so opening the page costs one
    request instead of one per patient.

    `attention` is an observation about the data, never a clinical
    instruction: it says what changed, and leaves the judgement to a person.
    """
    rows: list[dict] = []
    for patient in patients:
        sessions = completed_sessions(db, patient.id)
        briefs = [session_brief(s) for s in sessions]
        scored = [b for b in briefs if b["recovery_score"] is not None]
        trend = [round(b["recovery_score"]) for b in scored]
        latest = scored[-1] if scored else None

        attention, reason = "steady", "No change requiring review."
        if not scored:
            attention, reason = "new", "No analysable session recorded yet."
        elif latest and latest["confidence"] is not None and latest["confidence"] < 60:
            attention = "confidence"
            reason = (
                f"Signal confidence reduced — {latest['confidence']:.0f}% on the latest session."
            )
        elif len(scored) >= 2:
            first_sym = scored[0]["symmetry_index_pct"]
            last_sym = latest["symmetry_index_pct"] if latest else None
            if first_sym is not None and last_sym is not None:
                shift = last_sym - first_sym
                if abs(shift) >= 10:
                    attention = "review"
                    direction = "closer to" if shift > 0 else "further from"
                    reason = (
                        f"Symmetry moved {abs(shift):.0f} points {direction} 100% since the "
                        "first recorded session."
                    )
            if attention == "steady" and len(trend) >= 3 and trend[-1] > trend[0]:
                reason = f"Consistent upward trend across {len(trend)} recorded sessions."
        elif len(scored) == 1:
            attention, reason = "new", "First session recorded; no comparison available yet."

        initials = "·".join(part[0].upper() for part in patient.name.split()[:2] if part) or "—"
        # Weeks since surgery, when a date is recorded. None rather than 0 so
        # the interface can omit it instead of implying "week zero".
        weeks_post = None
        if patient.surgery_date is not None:
            delta_days = (datetime.now(timezone.utc).date() - patient.surgery_date).days
            weeks_post = max(0, delta_days // 7)
        rows.append(
            {
                "id": patient.id,
                "name": patient.name,
                "initials": initials,
                "operated_leg": patient.operated_leg.value if patient.operated_leg else None,
                "weeks_post": weeks_post,
                "sessions": len(sessions),
                "unusable_sessions": len(briefs) - len(scored),
                "trend": trend,
                "score": trend[-1] if trend else None,
                "latest_confidence": latest["confidence"] if latest else None,
                "attention": attention,
                "reason": reason,
            }
        )

    order = {"review": 0, "confidence": 1, "new": 2, "steady": 3}
    rows.sort(key=lambda r: (order.get(r["attention"], 9), -(r["score"] or 0)))
    return rows
