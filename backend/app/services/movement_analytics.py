"""Hardware-v2 movement analytics: per session, per patient, cohort, research.

Read-only. Every value is either carried straight from what the pipeline
stored (the session summary, activity windows, repetitions, raw-sample
chunks) or a plain aggregate of those values -- a mean, a count, a
least-squares slope -- computed here once so every page and the PDF agree.
Nothing is estimated, imputed or adjusted.

The "status" of a record (IMPROVING / STABLE / NEEDS_ATTENTION / COMPLETED)
is a stated rule over those aggregates (`STATUS_RULE`), an observation about
the stored data and not a clinical assessment.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db.models.base import as_utc, utc_iso
from app.db.models.patient import PatientProfile
from app.db.models.sensing import ActivityResult, SensorSampleChunk
from app.db.models.session import Session as SessionModel, SessionStatus
from app.sensing import provenance as prov
from app.services import authz

RESEARCH_LABEL = "Research indicators from a prototype pipeline. Not clinically validated."
SYNTHETIC_LABEL = "SYNTHETIC DEMONSTRATION DATA — NOT CLINICAL EVIDENCE"
REPLAY_LABEL = "PUBLIC DATASET REPLAY — NOT REHABSENSE HARDWARE DATA"
PROTOTYPE_NOTICE = "RehabSense is a research prototype and not a medical device."

STATUS_RULE = {
    "NEEDS_ATTENTION": ("current movement quality is 3+ points below the start, asymmetry is 3+ points "
                        "above the start, the last four sessions trend down by 1+ point per session, "
                        "or an ongoing programme has had no session for 7+ days"),
    "COMPLETED": "the programme period has ended and nothing above applies",
    "IMPROVING": "movement quality is 3+ points above the start and not trending down recently",
    "STABLE": "none of the above",
    "basis": ("start = mean of the first two sessions, current = mean of the last two; "
              "an observation about stored research indicators, not a clinical assessment"),
}


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and math.isfinite(x) else None


def _mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _sd(values) -> float | None:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def _round(x, n=1):
    return None if x is None else round(x, n)


def slope(xs: list[float], ys: list[float | None]) -> float | None:
    """Least-squares slope of y on x, ignoring missing y."""
    pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
    if len(pts) < 2:
        return None
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    den = sum((p[0] - mx) ** 2 for p in pts)
    if den == 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in pts) / den


# --------------------------------------------------------------------- #
# one session
# --------------------------------------------------------------------- #

def is_movement_session(session: SessionModel) -> bool:
    return (session.summary or {}).get("protocol_version") == 2


def session_metrics(session: SessionModel) -> dict | None:
    """The v2 indicators of one completed session, read from its summary."""
    s = session.summary or {}
    if s.get("protocol_version") != 2:
        return None
    mq = s.get("movement_quality") or {}
    bi = s.get("bilateral") or {}
    act = s.get("activity") or {}
    rs = s.get("repetition_summary") or {}
    conf = s.get("confidence") or {}
    cal = s.get("calibration") or {}
    stream = s.get("stream") or {}
    secs = {k: v for k, v in (act.get("seconds_by_activity") or {}).items() if v}
    top = max(secs.items(), key=lambda kv: kv[1])[0] if secs else None
    left, right = rs.get("LEFT") or {}, rs.get("RIGHT") or {}
    asym = _num(bi.get("asymmetry_score"))
    rom_l, rom_r = _num(left.get("rom_proxy_deg_mean")), _num(right.get("rom_proxy_deg_mean"))
    gen = session.generation or {}
    provenance = prov.of_session(session)
    return {
        "id": session.id,
        "patient_id": session.patient_id,
        "started_at": utc_iso(session.started_at),
        "ended_at": utc_iso(session.ended_at),
        "duration_s": _num(s.get("duration_s")) or session.duration_seconds,
        "exercise_type": session.exercise_type.value,
        "status": session.status.value,
        "provenance": provenance,
        "mqi": _num(mq.get("mqi")),
        "mqi_status": mq.get("status"),
        "mqi_confidence": _num(mq.get("confidence")),
        "mqi_components": mq.get("components") or {},
        "asymmetry_score": asym,
        "asymmetry_pct": None if asym is None else round(asym * 100, 1),
        "asymmetry_status": bi.get("status"),
        "asymmetry_confidence": _num(bi.get("confidence")),
        "repetitions": s.get("repetitions"),
        "repetition_kind": s.get("repetition_kind"),
        "reps_left": left.get("count"),
        "reps_right": right.get("count"),
        "rom_left_deg": rom_l,
        "rom_right_deg": rom_r,
        "rom_difference_deg": None if rom_l is None or rom_r is None else round(abs(rom_l - rom_r), 2),
        "rep_duration_left_s": _num(left.get("duration_s_mean")),
        "rep_duration_right_s": _num(right.get("duration_s_mean")),
        "sparc_left": _num(left.get("sparc_median")),
        "sparc_right": _num(right.get("sparc_median")),
        "peak_velocity_left_dps": _num(left.get("peak_velocity_dps_mean")),
        "peak_velocity_right_dps": _num(right.get("peak_velocity_dps_mean")),
        "activity_top": top,
        "activity_seconds": secs,
        "activity_windows": act.get("windows"),
        "low_confidence_windows": act.get("low_confidence_windows"),
        "model": act.get("model"),
        "model_unavailable_reason": act.get("unavailable_reason"),
        "confidence_pct": conf.get("percent"),
        "confidence_band": conf.get("band"),
        "bilateral_coverage": _num(conf.get("bilateral_coverage")),
        "calibration_status": (s.get("data_quality") or {}).get("calibration_status") or cal.get("status"),
        "calibration_quality": _num(cal.get("quality")),
        "packet_loss_pct": None if stream.get("loss_ratio") is None else round(stream["loss_ratio"] * 100, 2),
        "samples": stream.get("samples_accepted"),
        "reported_pain": session.reported_pain,
        "generated": bool(gen),
        "programme_day": gen.get("programme_day"),
    }


def generation_view(session: SessionModel) -> dict | None:
    """How a generated or replayed session was produced (null for recordings)."""
    gen = session.generation
    if not gen:
        return None
    keep = ("provenance", "label", "generator", "synthetic_generator_version", "seed", "session_seed",
            "source_dataset", "dataset_subject", "model_version", "pipeline_version",
            "generation_timestamp", "trajectory", "programme_day", "programme_days",
            "latent_impairment", "inputs", "segments", "stream", "note")
    return {k: gen[k] for k in keep if k in gen}


# --------------------------------------------------------------------- #
# one patient
# --------------------------------------------------------------------- #

def _completed_movement_sessions(db: DbSession, patient_ids: list[int] | None) -> list[SessionModel]:
    stmt = select(SessionModel).where(SessionModel.status == SessionStatus.COMPLETED,
                                      SessionModel.protocol_version == 2)
    if patient_ids is not None:
        if not patient_ids:
            return []
        stmt = stmt.where(SessionModel.patient_id.in_(patient_ids))
    rows = db.execute(stmt.order_by(SessionModel.started_at)).scalars().all()
    return [r for r in rows if is_movement_session(r)]


def _status(summary: dict, rows: list[dict], now: datetime) -> tuple[str, list[str]]:
    reasons: list[str] = []
    mqis = [r["mqi"] for r in rows if r["mqi"] is not None]
    recent = rows[-4:]
    recent_slope = slope(list(range(len(recent))), [r["mqi"] for r in recent]) if len(recent) >= 4 else None
    change = summary["mqi_change"]
    asym_change = summary["asymmetry_change_pct"]
    last = as_utc(datetime.fromisoformat(rows[-1]["started_at"].replace("Z", "+00:00"))) if rows else None
    days_since = None if last is None else (now - last).total_seconds() / 86400
    ended = summary.get("programme_ended")

    if change is not None and change <= -3:
        reasons.append(f"movement quality {change:+.1f} points since the start")
    if asym_change is not None and asym_change >= 3:
        reasons.append(f"asymmetry {asym_change:+.1f} points since the start")
    if recent_slope is not None and recent_slope <= -1.0:
        reasons.append(f"last four sessions trending down ({recent_slope:+.1f} points per session)")
    if not ended and days_since is not None and days_since >= 7:
        reasons.append(f"no session for {int(days_since)} days")
    if reasons:
        return "NEEDS_ATTENTION", reasons
    if ended:
        return "COMPLETED", [f"programme period ended ({summary['sessions_completed']} sessions)"]
    if change is not None and change >= 3 and (recent_slope is None or recent_slope > -0.5):
        return "IMPROVING", [f"movement quality {change:+.1f} points since the start"]
    if not mqis:
        return "STABLE", ["no movement-quality values yet"]
    return "STABLE", ["no sustained change in movement quality"]


def patient_movement(db: DbSession, patient: PatientProfile, sessions: list[SessionModel] | None = None,
                     now: datetime | None = None) -> dict:
    """Longitudinal v2 summary of one record."""
    now = now or datetime.now(timezone.utc)
    if sessions is None:
        sessions = _completed_movement_sessions(db, [patient.id])
    rows = [m for m in (session_metrics(s) for s in sessions) if m is not None]
    first = as_utc(sessions[0].started_at) if sessions else None
    days = [0.0 if first is None else (as_utc(s.started_at) - first).total_seconds() / 86400 for s in sessions]

    initial_mqi = _mean([r["mqi"] for r in rows[:2]])
    current_mqi = _mean([r["mqi"] for r in rows[-2:]])
    initial_asym = _mean([r["asymmetry_pct"] for r in rows[:2]])
    current_asym = _mean([r["asymmetry_pct"] for r in rows[-2:]])
    mqi_slope = slope(days, [r["mqi"] for r in rows])
    asym_slope = slope(days, [r["asymmetry_pct"] for r in rows])
    best = max((r for r in rows if r["mqi"] is not None), key=lambda r: r["mqi"], default=None)
    worst = min((r for r in rows if r["mqi"] is not None), key=lambda r: r["mqi"], default=None)
    span_days = (days[-1] + 1) if days else 0
    weeks = max(1.0, span_days / 7.0)

    start = patient.recovery_start or (first.date() if first else None)
    programme_end = (start + timedelta(days=patient.program_days - 1)
                     if start and patient.program_days else None)
    today = now.date()
    ended = programme_end is not None and programme_end < today
    if patient.planned_sessions and start and patient.program_days:
        elapsed = min(patient.program_days, max(1, (today - start).days + 1))
        expected = patient.planned_sessions * (1.0 if ended else elapsed / patient.program_days)
        adherence = min(100.0, 100.0 * len(rows) / max(1.0, expected))
    else:
        expected, adherence = None, None

    activity = Counter()
    for r in rows:
        activity.update(r["activity_seconds"])
    exercises = Counter(r["exercise_type"] for r in rows)
    provs = Counter(r["provenance"] for r in rows)

    summary = {
        "programme": patient.program,
        "programme_days": patient.program_days,
        "planned_sessions": patient.planned_sessions,
        "start_date": start.isoformat() if start else None,
        "programme_end": programme_end.isoformat() if programme_end else None,
        "programme_ended": ended,
        "duration_days": int(round(span_days)) if rows else 0,
        "sessions_completed": len(rows),
        "expected_sessions_to_date": None if expected is None else round(expected, 1),
        "adherence_pct": _round(adherence),
        "initial_mqi": _round(initial_mqi),
        "current_mqi": _round(current_mqi),
        "mqi_change": _round(None if initial_mqi is None or current_mqi is None else current_mqi - initial_mqi),
        "improvement_pct": _round(None if not initial_mqi or current_mqi is None
                                  else 100.0 * (current_mqi - initial_mqi) / initial_mqi),
        "initial_asymmetry_pct": _round(initial_asym),
        "current_asymmetry_pct": _round(current_asym),
        "asymmetry_change_pct": _round(None if initial_asym is None or current_asym is None
                                       else current_asym - initial_asym),
        "mqi_slope_per_week": _round(None if mqi_slope is None else mqi_slope * 7, 2),
        "asymmetry_slope_per_week": _round(None if asym_slope is None else asym_slope * 7, 2),
        "mqi_trend": _direction(mqi_slope, higher_is_better=True),
        "asymmetry_trend": _direction(asym_slope, higher_is_better=False),
        "best_session": None if best is None else {"id": best["id"], "mqi": best["mqi"],
                                                   "started_at": best["started_at"],
                                                   "exercise_type": best["exercise_type"]},
        "worst_session": None if worst is None else {"id": worst["id"], "mqi": worst["mqi"],
                                                     "started_at": worst["started_at"],
                                                     "exercise_type": worst["exercise_type"]},
        "consistency_sd": _round(_sd([r["mqi"] for r in rows[-6:]])),
        "sessions_per_week": _round(len(rows) / weeks, 2),
        "mean_repetitions": _round(_mean([r["repetitions"] for r in rows])),
        "mean_duration_s": _round(_mean([r["duration_s"] for r in rows])),
        "mean_confidence_pct": _round(_mean([r["confidence_pct"] for r in rows])),
        "activity_seconds": dict(activity.most_common()),
        "exercises": dict(exercises.most_common()),
        "provenance": provs.most_common(1)[0][0] if provs else patient.provenance,
        "provenance_counts": dict(provs),
        "models": sorted({r["model"] for r in rows if r["model"]}),
        "last_session_at": rows[-1]["started_at"] if rows else None,
        "last_activity": rows[-1]["activity_top"] if rows else None,
    }
    status, reasons = _status(summary, rows, now) if rows else ("STABLE", ["no sessions yet"])
    summary["status"] = status
    summary["status_reasons"] = reasons
    return {
        "patient": patient_brief(patient),
        "summary": summary,
        "sessions": rows,
        "status_rule": STATUS_RULE,
        "labels": labels_for(summary["provenance"]),
    }


def _direction(value: float | None, *, higher_is_better: bool) -> str:
    """Per-day slope -> words. 0.1 point/day = 0.7 points/week."""
    if value is None:
        return "insufficient"
    if abs(value) < 0.1:
        return "flat"
    good = value > 0 if higher_is_better else value < 0
    return "improving" if good else "worsening"


def patient_brief(patient: PatientProfile) -> dict:
    return {
        "id": patient.id, "name": patient.name, "preferred_name": patient.preferred_name,
        "age": patient.age, "operated_leg": patient.operated_leg.value,
        "program": patient.program, "program_days": patient.program_days,
        "planned_sessions": patient.planned_sessions,
        "recovery_start": patient.recovery_start.isoformat() if patient.recovery_start else None,
        "provenance": patient.provenance,
    }


def labels_for(provenance: str | None) -> dict:
    if provenance == prov.SYNTHETIC_DEMONSTRATION:
        primary = SYNTHETIC_LABEL
    elif provenance == prov.PUBLIC_DATASET_REPLAY:
        primary = REPLAY_LABEL
    elif provenance == prov.SIMULATED:
        primary = "SIMULATED SENSOR STREAM — NOT PHYSICAL HARDWARE DATA"
    else:
        primary = None
    return {"provenance": primary, "research": RESEARCH_LABEL, "prototype": PROTOTYPE_NOTICE,
            "provenance_detail": prov.DESCRIPTION.get(provenance or "", None)}


# --------------------------------------------------------------------- #
# what a user may see
# --------------------------------------------------------------------- #

def visible_patients(db: DbSession, user) -> list[PatientProfile]:
    allowed = authz.visible_patient_ids(db, user)
    stmt = select(PatientProfile)
    if allowed is not None:
        if not allowed:
            return []
        stmt = stmt.where(PatientProfile.id.in_(allowed))
    return list(db.execute(stmt.order_by(PatientProfile.id)).scalars())


def _by_patient(sessions: list[SessionModel]) -> dict[int, list[SessionModel]]:
    out: dict[int, list[SessionModel]] = defaultdict(list)
    for s in sessions:
        out[s.patient_id].append(s)
    return out


def roster(db: DbSession, user, now: datetime | None = None) -> dict:
    patients = visible_patients(db, user)
    sessions = _completed_movement_sessions(db, [p.id for p in patients])
    grouped = _by_patient(sessions)
    items, references = [], []
    for p in patients:
        mv = patient_movement(db, p, grouped.get(p.id, []), now=now)
        series = [{"id": r["id"], "started_at": r["started_at"], "mqi": r["mqi"],
                   "asymmetry_pct": r["asymmetry_pct"]} for r in mv["sessions"]]
        entry = {**mv["patient"], **{k: mv["summary"][k] for k in (
            "sessions_completed", "last_session_at", "current_mqi", "initial_mqi", "mqi_change",
            "mqi_trend", "current_asymmetry_pct", "asymmetry_trend", "status", "status_reasons",
            "last_activity", "adherence_pct", "programme_ended")}, "series": series}
        (references if p.provenance == prov.PUBLIC_DATASET_REPLAY else items).append(entry)
    order = {"NEEDS_ATTENTION": 0, "IMPROVING": 1, "STABLE": 2, "COMPLETED": 3}
    items.sort(key=lambda e: (order.get(e["status"], 9), -(e["sessions_completed"] or 0)))
    return {"items": items, "references": references, "status_rule": STATUS_RULE,
            "synthetic": any(p.provenance == prov.SYNTHETIC_DEMONSTRATION for p in patients)}


# --------------------------------------------------------------------- #
# cohort overview
# --------------------------------------------------------------------- #

def _inference_counts(db: DbSession, session_ids: list[int]) -> dict:
    if not session_ids:
        return {"total": 0, "by_status": {}, "by_activity": {}, "by_model": {}}
    rows = db.execute(
        select(ActivityResult.status, ActivityResult.activity, ActivityResult.model_ref,
               func.count(ActivityResult.id))
        .where(ActivityResult.session_id.in_(session_ids))
        .group_by(ActivityResult.status, ActivityResult.activity, ActivityResult.model_ref)
    ).all()
    by_status, by_activity, by_model = Counter(), Counter(), Counter()
    for status, activity, model, n in rows:
        by_status[status.value] += n
        if activity:
            by_activity[activity] += n
        if model:
            by_model[model] += n
    return {"total": sum(by_status.values()), "by_status": dict(by_status),
            "by_activity": dict(by_activity.most_common()), "by_model": dict(by_model)}


def _samples(db: DbSession, session_ids: list[int]) -> dict:
    if not session_ids:
        return {"samples": 0, "chunks": 0}
    n, chunks = db.execute(select(func.coalesce(func.sum(SensorSampleChunk.n_samples), 0),
                                  func.count(SensorSampleChunk.id))
                           .where(SensorSampleChunk.session_id.in_(session_ids))).one()
    return {"samples": int(n or 0), "chunks": int(chunks or 0)}


def overview(db: DbSession, user, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    patients = visible_patients(db, user)
    sessions = _completed_movement_sessions(db, [p.id for p in patients])
    grouped = _by_patient(sessions)
    cohort = [p for p in patients if p.provenance != prov.PUBLIC_DATASET_REPLAY]
    cohort_ids = {p.id for p in cohort}
    movement = {p.id: patient_movement(db, p, grouped.get(p.id, []), now=now) for p in cohort}
    cohort_sessions = [s for s in sessions if s.patient_id in cohort_ids]
    rows = [m for m in (session_metrics(s) for s in cohort_sessions) if m]
    week_ago = now - timedelta(days=7)
    this_week = [s for s in cohort_sessions if as_utc(s.started_at) >= week_ago]
    statuses = Counter(m["summary"]["status"] for m in movement.values() if m["summary"]["sessions_completed"])
    current = [m["summary"]["current_mqi"] for m in movement.values()]
    current_asym = [m["summary"]["current_asymmetry_pct"] for m in movement.values()]
    changes = [m["summary"]["mqi_change"] for m in movement.values()]

    # Cohort mean movement quality per ISO week, from every session that week.
    weekly: dict[str, list[float]] = defaultdict(list)
    weekly_asym: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        at = datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))
        monday = (at - timedelta(days=at.weekday())).date().isoformat()
        if r["mqi"] is not None:
            weekly[monday].append(r["mqi"])
        if r["asymmetry_pct"] is not None:
            weekly_asym[monday].append(r["asymmetry_pct"])
    trend = [{"week": w, "mean_mqi": _round(_mean(v)), "mean_asymmetry_pct": _round(_mean(weekly_asym[w])),
              "sessions": len(v)} for w, v in sorted(weekly.items())]

    names = {p.id: p.name for p in patients}
    recent = sorted(rows, key=lambda r: r["started_at"], reverse=True)[:8]
    attention = [{"patient_id": pid, "name": names[pid], "reasons": m["summary"]["status_reasons"],
                  "current_mqi": m["summary"]["current_mqi"],
                  "current_asymmetry_pct": m["summary"]["current_asymmetry_pct"]}
                 for pid, m in movement.items() if m["summary"]["status"] == "NEEDS_ATTENTION"]
    all_ids = [s.id for s in sessions]
    provenance_sessions = Counter(prov.of_session(s) for s in sessions)
    provenance_records = Counter(p.provenance or "REAL_RECORD" for p in patients)
    return {
        "generated_at": utc_iso(now),
        "kpis": {
            "active_patients": sum(1 for m in movement.values()
                                   if m["summary"]["sessions_completed"] and not m["summary"]["programme_ended"]),
            "patients": len(cohort),
            "sessions_this_week": len(this_week),
            "total_sessions": len(cohort_sessions),
            "sessions_completed": len(rows),
            "average_mqi": _round(_mean(current)),
            "average_asymmetry_pct": _round(_mean(current_asym)),
            "average_mqi_change": _round(_mean(changes)),
            "improving": statuses.get("IMPROVING", 0),
            "stable": statuses.get("STABLE", 0),
            "needs_attention": statuses.get("NEEDS_ATTENTION", 0),
            "completed": statuses.get("COMPLETED", 0),
            "exercises_performed": len({r["exercise_type"] for r in rows}),
            "model_inferences": _inference_counts(db, [s.id for s in cohort_sessions])["total"],
            "total_repetitions": sum(r["repetitions"] or 0 for r in rows),
        },
        "exercise_counts": dict(Counter(r["exercise_type"] for r in rows).most_common()),
        "weekly_trend": trend,
        "recent_sessions": [{**r, "patient_name": names.get(r["patient_id"])} for r in recent],
        "needs_attention": attention,
        "patients": [{**movement[p.id]["patient"], "status": movement[p.id]["summary"]["status"],
                      "current_mqi": movement[p.id]["summary"]["current_mqi"],
                      "mqi_change": movement[p.id]["summary"]["mqi_change"],
                      "series": [r["mqi"] for r in movement[p.id]["sessions"]]} for p in cohort],
        "provenance": {"sessions": dict(provenance_sessions), "records": dict(provenance_records),
                       "all_sessions": len(all_ids)},
        "synthetic": any(p.provenance == prov.SYNTHETIC_DEMONSTRATION for p in patients),
        "labels": labels_for(prov.SYNTHETIC_DEMONSTRATION if any(
            p.provenance == prov.SYNTHETIC_DEMONSTRATION for p in cohort) else None),
        "status_rule": STATUS_RULE,
    }


# --------------------------------------------------------------------- #
# sessions table
# --------------------------------------------------------------------- #

def session_rows(db: DbSession, user, patient_id: int | None = None, limit: int = 500) -> dict:
    patients = visible_patients(db, user)
    ids = [p.id for p in patients]
    if patient_id is not None:
        if patient_id not in ids:
            return {"items": [], "total": 0}
        ids = [patient_id]
    sessions = _completed_movement_sessions(db, ids)
    names = {p.id: p.name for p in patients}
    rows = [{**m, "patient_name": names.get(m["patient_id"])}
            for m in (session_metrics(s) for s in reversed(sessions)) if m]
    return {"items": rows[:limit], "total": len(rows)}


# --------------------------------------------------------------------- #
# exercises
# --------------------------------------------------------------------- #

def exercises(db: DbSession, user) -> dict:
    patients = [p for p in visible_patients(db, user) if p.provenance != prov.PUBLIC_DATASET_REPLAY]
    names = {p.id: p.name for p in patients}
    sessions = _completed_movement_sessions(db, list(names))
    by_ex: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        m = session_metrics(s)
        if m:
            by_ex[m["exercise_type"]].append(m)
    items = []
    for ex, rows in sorted(by_ex.items(), key=lambda kv: -len(kv[1])):
        rows.sort(key=lambda r: r["started_at"])
        # Trend within each record, then averaged: pooling records would turn
        # differences between people into a fake trend over time.
        per_patient = defaultdict(list)
        for r in rows:
            per_patient[r["patient_id"]].append(r)
        slopes = [slope(list(range(len(v))), [r["mqi"] for r in v]) for v in per_patient.values() if len(v) >= 2]
        mean_slope = _mean(slopes)
        predicted = Counter()
        for r in rows:
            predicted.update(r["activity_seconds"])
        items.append({
            "exercise_type": ex,
            "sessions": len(rows),
            "patients": len(per_patient),
            "patient_names": sorted(names[pid] for pid in per_patient),
            "average_repetitions": _round(_mean([r["repetitions"] for r in rows])),
            "average_mqi": _round(_mean([r["mqi"] for r in rows])),
            "average_asymmetry_pct": _round(_mean([r["asymmetry_pct"] for r in rows])),
            "average_duration_s": _round(_mean([r["duration_s"] for r in rows])),
            "average_rep_duration_s": _round(_mean([_mean([r["rep_duration_left_s"], r["rep_duration_right_s"]])
                                                    for r in rows]), 2),
            "mqi_slope_per_session": _round(mean_slope, 2),
            "trend": "insufficient" if mean_slope is None else
                     "improving" if mean_slope >= 0.3 else "worsening" if mean_slope <= -0.3 else "flat",
            "model_activity_seconds": dict(predicted.most_common()),
            "series": [{"started_at": r["started_at"], "mqi": r["mqi"], "patient_id": r["patient_id"]}
                       for r in rows],
        })
    return {"items": items, "note": ("Per-exercise averages over every completed hardware-v2 session "
                                     "you can see. The trend is the mean of each record's own "
                                     "session-to-session slope."),
            "labels": labels_for(prov.SYNTHETIC_DEMONSTRATION if any(
                p.provenance == prov.SYNTHETIC_DEMONSTRATION for p in patients) else None)}


# --------------------------------------------------------------------- #
# research
# --------------------------------------------------------------------- #

def _histogram(values: list[float], lo: float, hi: float, bins: int) -> list[dict]:
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        if v is None:
            continue
        i = int((v - lo) / width)
        counts[min(bins - 1, max(0, i))] += 1
    return [{"from": round(lo + i * width, 3), "to": round(lo + (i + 1) * width, 3), "count": c}
            for i, c in enumerate(counts)]


def replay_agreement(db: DbSession, sessions: list[SessionModel]) -> dict:
    """Model output vs the public dataset's own labels, window by window.

    Only windows lying wholly inside one labelled segment are scored, and only
    activities the model has a class for. Measured on data the model was
    trained on: a pipeline-integrity check, not an accuracy estimate.
    """
    scored = Counter()
    confusion: dict[str, Counter] = defaultdict(Counter)
    for s in sessions:
        segments = (s.generation or {}).get("segments") or []
        if not segments:
            continue
        windows = db.execute(select(ActivityResult).where(ActivityResult.session_id == s.id)).scalars()
        for w in windows:
            seg = next((g for g in segments if g["t_start"] <= w.t_start and w.t_end <= g["t_end"]), None)
            if seg is None:
                continue   # straddles two labelled segments: no single truth to score against
            truth = seg["label"]
            if w.status.value == "OK":
                confusion[truth][w.activity or "?"] += 1
                scored["correct" if w.activity == truth else "wrong"] += 1
            else:
                confusion[truth]["(low confidence)"] += 1
                scored["low_confidence"] += 1
    total = sum(scored.values())
    return {
        "windows_scored": total,
        "agreement_pct": None if not total else round(100.0 * scored["correct"] / total, 1),
        "low_confidence_pct": None if not total else round(100.0 * scored["low_confidence"] / total, 1),
        "confusion": {k: dict(v.most_common()) for k, v in confusion.items()},
        "scope": ("Replayed public recordings the model was trained on, subjects included. Checks that "
                  "the device pipeline feeds the model correctly; not a generalisation estimate and "
                  "not RehabSense hardware validation."),
    }


def research(db: DbSession, user, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    patients = visible_patients(db, user)
    sessions = _completed_movement_sessions(db, [p.id for p in patients])
    ids = [s.id for s in sessions]
    rows = [m for m in (session_metrics(s) for s in sessions) if m]
    by_prov: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_prov[r["provenance"]].append(r)
    synthetic = [r for r in rows if r["provenance"] != prov.PUBLIC_DATASET_REPLAY]
    replay_sessions = [s for s in sessions if prov.of_session(s) == prov.PUBLIC_DATASET_REPLAY]

    conf_values = db.execute(select(ActivityResult.confidence).where(
        ActivityResult.session_id.in_(ids or [-1]), ActivityResult.confidence.is_not(None))).scalars().all()
    inference = _inference_counts(db, ids)
    per_prov_inference = {p: _inference_counts(db, [r["id"] for r in rs]) for p, rs in by_prov.items()}

    grouped = _by_patient(sessions)
    longitudinal = []
    for p in patients:
        if p.provenance == prov.PUBLIC_DATASET_REPLAY or not grouped.get(p.id):
            continue
        mv = patient_movement(db, p, grouped[p.id], now=now)
        sm = mv["summary"]
        longitudinal.append({
            "patient_id": p.id, "name": p.name, "provenance": p.provenance,
            "status": sm["status"], "mqi_trend": sm["mqi_trend"], "asymmetry_trend": sm["asymmetry_trend"],
            "mqi_slope_per_week": sm["mqi_slope_per_week"],
            "asymmetry_slope_per_week": sm["asymmetry_slope_per_week"],
            "initial_mqi": sm["initial_mqi"], "current_mqi": sm["current_mqi"],
            "adherence_pct": sm["adherence_pct"], "sessions": sm["sessions_completed"],
            "consistency_sd": sm["consistency_sd"],
            "series": [{"day": r["programme_day"], "started_at": r["started_at"], "mqi": r["mqi"],
                        "asymmetry_pct": r["asymmetry_pct"]} for r in mv["sessions"]],
        })
    trajectories = Counter(item["mqi_trend"] for item in longitudinal)

    variability = defaultdict(list)
    for r in synthetic:
        variability[r["patient_id"]].append(r["mqi"])
    return {
        "generated_at": utc_iso(now),
        "dataset": {
            "sessions": len(rows),
            "sessions_by_provenance": {p: len(v) for p, v in by_prov.items()},
            "records_by_provenance": dict(Counter(p.provenance or "REAL_RECORD" for p in patients)),
            "patients": sum(1 for p in patients if p.provenance != prov.PUBLIC_DATASET_REPLAY),
            **_samples(db, ids),
            "activities": sorted(inference["by_activity"]),
            "exercises": dict(Counter(r["exercise_type"] for r in rows).most_common()),
            "model_versions": sorted({r["model"] for r in rows if r["model"]}),
            "physical_sessions": sum(1 for r in rows if prov.counts_as_physical_evidence(r["provenance"])),
        },
        "model": {
            **inference,
            "by_provenance": per_prov_inference,
            "confidence_histogram": _histogram(conf_values, 0.0, 1.0, 10),
            "mean_confidence": _round(_mean(conf_values), 3),
            "replay_agreement": replay_agreement(db, replay_sessions),
            "note": ("Public-dataset performance is not RehabSense hardware performance. On synthetic "
                     "signals the model reports what it sees; those labels are not checked against "
                     "any ground truth."),
        },
        "movement": {
            "mqi_histogram": _histogram([r["mqi"] for r in synthetic], 40.0, 100.0, 12),
            "asymmetry_histogram": _histogram([r["asymmetry_pct"] for r in synthetic], 0.0, 60.0, 12),
            "mean_mqi": _round(_mean([r["mqi"] for r in synthetic])),
            "mean_asymmetry_pct": _round(_mean([r["asymmetry_pct"] for r in synthetic])),
            "mqi_sd_by_patient": {pid: _round(_sd(v)) for pid, v in variability.items()},
            "rep_duration_by_exercise": {ex: _round(_mean([_mean([r["rep_duration_left_s"], r["rep_duration_right_s"]])
                                                           for r in synthetic if r["exercise_type"] == ex]), 2)
                                         for ex in sorted({r["exercise_type"] for r in synthetic})},
            "left_right_rom_difference_deg": _round(_mean([r["rom_difference_deg"] for r in synthetic]), 2),
            "points": [{"id": r["id"], "patient_id": r["patient_id"], "mqi": r["mqi"],
                        "asymmetry_pct": r["asymmetry_pct"], "exercise_type": r["exercise_type"],
                        "rom_left_deg": r["rom_left_deg"], "rom_right_deg": r["rom_right_deg"]}
                       for r in synthetic],
            "components_mean": {k: _round(_mean([(r["mqi_components"] or {}).get(k) for r in synthetic]), 3)
                                for k in ("symmetry", "temporal_consistency", "smoothness",
                                          "force_consistency", "repetition_consistency",
                                          "rom_proxy_vs_baseline")},
        },
        "longitudinal": {
            "records": longitudinal,
            "trajectories": dict(trajectories),
            "mean_adherence_pct": _round(_mean([i["adherence_pct"] for i in longitudinal])),
        },
        "labels": labels_for(prov.SYNTHETIC_DEMONSTRATION if any(
            p.provenance == prov.SYNTHETIC_DEMONSTRATION for p in patients) else None),
        "validation": {"public_dataset": "EVALUATED (see the model bundle)", "rehabsense_hardware": "NOT_VALIDATED",
                       "clinical": "NOT_VALIDATED"},
    }
