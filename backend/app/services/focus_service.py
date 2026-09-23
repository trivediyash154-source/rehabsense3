"""Recovery Focus: planning, timing and adherence.

Two rules shape this module.

**Timing is derived, never counted.** Every duration comes from the
`FocusEvent` ledger, so a refresh, a navigation, a sleeping laptop or a
backend restart cannot corrupt it. Nothing anywhere increments a second.

**Movement numbers belong to the session.** Repetitions, ROM and quality are
read from the linked `Session` rows. Focus reports how long the patient
worked and how that compares with their plan; it never recomputes what the
analytics pipeline already decided.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession, selectinload

from app.core.exceptions import Conflict, NotFound
from app.db.models.base import as_utc
from app.db.models.focus import (
    FocusEvent,
    FocusEventKind,
    FocusReminder,
    FocusSession,
    FocusStatus,
)
from app.db.models.session import Session as SessionModel, SessionStatus

# A block left open longer than this was almost certainly abandoned rather
# than worked through, so it is reported as INTERRUPTED instead of quietly
# accruing adherence for hours the patient did not spend exercising.
STALE_AFTER_S = 6 * 3600

# Presets offered by the UI. Custom values are accepted; these are the
# shortcuts, not the limit.
PRESET_DURATIONS_S = [300, 600, 900, 1200, 1500, 1800, 2700, 3600]
MIN_TARGET_S = 60
MAX_TARGET_S = 6 * 3600

# Share of the target that counts the day as adhered-to. Explicit, and
# reported alongside every streak so the rule is never implicit.
ADHERENCE_THRESHOLD = 0.8


class FocusNotFound(NotFound):
    code = "FOCUS_NOT_FOUND"
    detail = "No such focus block."


@dataclass
class Timing:
    """Derived durations for one block. Every field comes from timestamps."""

    elapsed_s: float
    paused_s: float
    engaged_s: float
    active_movement_s: float
    completion_pct: float
    interruptions: int
    is_running: bool


def _events(focus: FocusSession) -> list[FocusEvent]:
    return sorted(focus.events, key=lambda e: (as_utc(e.at), e.id))


def compute_timing(focus: FocusSession, *, now: datetime | None = None) -> Timing:
    """Reconstruct a block's durations from its ledger.

    `engaged` is wall time minus paused time -- the time the patient was
    actually in a running block. `active_movement` is the time sensors were
    recording, summed from the linked sessions. They are different numbers
    and the interface shows both, because "the block ran for 28 minutes" and
    "the limbs moved for 26 of them" are different claims.
    """
    now = now or datetime.now(timezone.utc)
    started = as_utc(focus.started_at)
    if started is None:
        return Timing(0.0, 0.0, 0.0, 0.0, 0.0, 0, False)

    ended = as_utc(focus.ended_at)
    boundary = ended or now
    elapsed = max(0.0, (boundary - started).total_seconds())

    paused = 0.0
    interruptions = 0
    pause_open: datetime | None = None
    for event in _events(focus):
        at = as_utc(event.at)
        if at is None:
            continue
        if event.kind is FocusEventKind.PAUSED and pause_open is None:
            pause_open = at
            interruptions += 1
        elif event.kind is FocusEventKind.RESUMED and pause_open is not None:
            paused += max(0.0, (at - pause_open).total_seconds())
            pause_open = None
    if pause_open is not None:
        # Still paused: the pause runs up to the boundary.
        paused += max(0.0, (boundary - pause_open).total_seconds())

    paused = min(paused, elapsed)
    engaged = max(0.0, elapsed - paused)

    active = 0.0
    for session in focus.sessions:
        seconds = session.duration_seconds
        if seconds:
            active += seconds
    # A session cannot have moved for longer than the block was running.
    active = min(active, engaged) if engaged else active

    target = max(1, focus.target_duration_s)
    completion = round(min(engaged / target, 4.0) * 100, 1)

    return Timing(
        elapsed_s=round(elapsed, 1),
        paused_s=round(paused, 1),
        engaged_s=round(engaged, 1),
        active_movement_s=round(active, 1),
        completion_pct=completion,
        interruptions=interruptions,
        is_running=focus.status is FocusStatus.ACTIVE,
    )


def session_rollup(focus: FocusSession) -> dict:
    """Movement totals, read straight from the linked sessions."""
    reps = 0
    exercises: list[str] = []
    roms: list[float] = []
    confidences: list[float] = []
    completed = 0
    for session in focus.sessions:
        exercises.append(session.exercise_type.value)
        if session.status is SessionStatus.COMPLETED:
            completed += 1
        summary = session.summary or {}
        if summary.get("repetitions"):
            reps += int(summary["repetitions"])
        if summary.get("rom_deg") is not None:
            roms.append(float(summary["rom_deg"]))
        conf = (session.confidence or {}).get("percent")
        if conf is not None:
            confidences.append(float(conf))

    return {
        "session_count": len(focus.sessions),
        "completed_session_count": completed,
        "repetitions": reps,
        "exercises": sorted(set(exercises)),
        "exercise_count": len(set(exercises)),
        # None rather than 0: no measurement is not a measurement of zero.
        "best_rom_deg": round(max(roms), 2) if roms else None,
        "mean_confidence_pct": round(sum(confidences) / len(confidences), 1) if confidences else None,
        "session_ids": [s.id for s in focus.sessions],
    }


def serialise(focus: FocusSession, *, now: datetime | None = None) -> dict:
    timing = compute_timing(focus, now=now)
    rollup = session_rollup(focus)
    started = as_utc(focus.started_at)
    ended = as_utc(focus.ended_at)
    return {
        "id": focus.id,
        "patient_id": focus.patient_id,
        "status": focus.status.value,
        "exercise_type": focus.exercise_type.value,
        "local_date": focus.local_date,
        "target_duration_s": focus.target_duration_s,
        "scheduled_for": _iso(as_utc(focus.scheduled_for)),
        "started_at": _iso(started),
        "ended_at": _iso(ended),
        "notes": focus.notes,
        # --- derived timing (§8: three distinct durations) ---
        "elapsed_s": timing.elapsed_s,
        "paused_s": timing.paused_s,
        "engaged_s": timing.engaged_s,
        "active_movement_s": timing.active_movement_s,
        "remaining_s": max(0.0, round(focus.target_duration_s - timing.engaged_s, 1)),
        "completion_pct": timing.completion_pct,
        "interruptions": timing.interruptions,
        "is_running": timing.is_running,
        # --- movement, from the sessions themselves ---
        **rollup,
        "adherence_threshold_pct": round(ADHERENCE_THRESHOLD * 100),
        "met_target": timing.completion_pct >= ADHERENCE_THRESHOLD * 100,
    }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


# --- lifecycle ------------------------------------------------------------ #

def _record(db: DbSession, focus: FocusSession, kind: FocusEventKind, at: datetime) -> None:
    db.add(FocusEvent(focus_id=focus.id, kind=kind, at=at))


def create(
    db: DbSession,
    *,
    patient_id: int,
    actor_id: int | None,
    target_duration_s: int,
    exercise_type,
    local_date: str,
    scheduled_for: datetime | None = None,
    notes: str | None = None,
) -> FocusSession:
    if not (MIN_TARGET_S <= target_duration_s <= MAX_TARGET_S):
        raise Conflict(
            f"Target must be between {MIN_TARGET_S // 60} and {MAX_TARGET_S // 60} minutes."
        )
    focus = FocusSession(
        patient_id=patient_id,
        created_by=actor_id,
        target_duration_s=int(target_duration_s),
        exercise_type=exercise_type,
        local_date=local_date,
        scheduled_for=scheduled_for,
        notes=notes,
        status=FocusStatus.READY,
    )
    db.add(focus)
    db.flush()
    return focus


def start(db: DbSession, focus: FocusSession, *, now: datetime | None = None) -> FocusSession:
    now = now or datetime.now(timezone.utc)
    if focus.status in (FocusStatus.COMPLETED, FocusStatus.CANCELLED):
        raise Conflict("This focus block has already finished.")
    if focus.status is FocusStatus.ACTIVE:
        return focus
    if focus.status is FocusStatus.PAUSED:
        return resume(db, focus, now=now)
    focus.status = FocusStatus.ACTIVE
    focus.started_at = now
    _record(db, focus, FocusEventKind.STARTED, now)
    return focus


def pause(db: DbSession, focus: FocusSession, *, now: datetime | None = None) -> FocusSession:
    now = now or datetime.now(timezone.utc)
    if focus.status is not FocusStatus.ACTIVE:
        raise Conflict("Only a running focus block can be paused.")
    focus.status = FocusStatus.PAUSED
    _record(db, focus, FocusEventKind.PAUSED, now)
    return focus


def resume(db: DbSession, focus: FocusSession, *, now: datetime | None = None) -> FocusSession:
    now = now or datetime.now(timezone.utc)
    if focus.status is not FocusStatus.PAUSED:
        raise Conflict("Only a paused focus block can be resumed.")
    focus.status = FocusStatus.ACTIVE
    _record(db, focus, FocusEventKind.RESUMED, now)
    return focus


def complete(db: DbSession, focus: FocusSession, *, now: datetime | None = None) -> FocusSession:
    now = now or datetime.now(timezone.utc)
    if focus.status in (FocusStatus.COMPLETED, FocusStatus.CANCELLED):
        raise Conflict("This focus block has already finished.")
    if focus.started_at is None:
        raise Conflict("This focus block was never started.")
    if focus.status is FocusStatus.PAUSED:
        # Close the open pause so paused time stops at the moment of ending.
        _record(db, focus, FocusEventKind.RESUMED, now)
    focus.status = FocusStatus.COMPLETED
    focus.ended_at = now
    _record(db, focus, FocusEventKind.COMPLETED, now)
    return focus


def cancel(db: DbSession, focus: FocusSession, *, now: datetime | None = None) -> FocusSession:
    now = now or datetime.now(timezone.utc)
    if focus.status in (FocusStatus.COMPLETED, FocusStatus.CANCELLED):
        raise Conflict("This focus block has already finished.")
    focus.status = FocusStatus.CANCELLED
    focus.ended_at = now
    _record(db, focus, FocusEventKind.CANCELLED, now)
    return focus


def reap_stale(db: DbSession, patient_id: int, *, now: datetime | None = None) -> int:
    """Close blocks left open far too long, as INTERRUPTED rather than done.

    Someone who closed the tab mid-session has not adhered to a six-hour
    block, and counting it that way would make the whole adherence record
    dishonest.
    """
    now = now or datetime.now(timezone.utc)
    stmt = (
        select(FocusSession)
        .where(
            FocusSession.patient_id == patient_id,
            FocusSession.status.in_([FocusStatus.ACTIVE, FocusStatus.PAUSED]),
        )
        .options(selectinload(FocusSession.events), selectinload(FocusSession.sessions))
    )
    closed = 0
    for focus in db.execute(stmt).scalars():
        started = as_utc(focus.started_at)
        if started and (now - started).total_seconds() > STALE_AFTER_S:
            focus.status = FocusStatus.INTERRUPTED
            focus.ended_at = now
            _record(db, focus, FocusEventKind.INTERRUPTED, now)
            closed += 1
    return closed


# --- queries -------------------------------------------------------------- #

def _loaded(stmt):
    return stmt.options(
        selectinload(FocusSession.events), selectinload(FocusSession.sessions)
    )


def get(db: DbSession, focus_id: int) -> FocusSession:
    focus = db.execute(
        _loaded(select(FocusSession).where(FocusSession.id == focus_id))
    ).scalar_one_or_none()
    if focus is None:
        raise FocusNotFound()
    return focus


def for_date(db: DbSession, patient_id: int, local_date: str) -> list[FocusSession]:
    stmt = _loaded(
        select(FocusSession)
        .where(FocusSession.patient_id == patient_id, FocusSession.local_date == local_date)
        .order_by(FocusSession.created_at)
    )
    return list(db.execute(stmt).scalars())


def in_range(db: DbSession, patient_id: int, start_date: str, end_date: str) -> list[FocusSession]:
    stmt = _loaded(
        select(FocusSession)
        .where(
            FocusSession.patient_id == patient_id,
            FocusSession.local_date >= start_date,
            FocusSession.local_date <= end_date,
        )
        .order_by(FocusSession.local_date, FocusSession.created_at)
    )
    return list(db.execute(stmt).scalars())


# --- adherence ------------------------------------------------------------ #

def day_summary(blocks: list[FocusSession], local_date: str, *, now=None) -> dict:
    """Adherence for one calendar day, aggregated over its blocks."""
    planned = 0
    engaged = 0.0
    active = 0.0
    reps = 0
    exercises: list[str] = []
    entries = []
    counted = 0

    for focus in blocks:
        timing = compute_timing(focus, now=now)
        rollup = session_rollup(focus)
        planned += focus.target_duration_s
        engaged += timing.engaged_s
        active += timing.active_movement_s
        reps += rollup["repetitions"]
        exercises.extend(rollup["exercises"])
        if focus.status is FocusStatus.COMPLETED:
            counted += 1
        started = as_utc(focus.started_at)
        entries.append({
            "focus_id": focus.id,
            "status": focus.status.value,
            "exercise_type": focus.exercise_type.value,
            "started_at": _iso(started),
            # Minutes past local midnight, so the timeline can place the block
            # without the browser re-deriving it from a timezone.
            "start_minute": (started.hour * 60 + started.minute) if started else None,
            "target_duration_s": focus.target_duration_s,
            "engaged_s": timing.engaged_s,
            "active_movement_s": timing.active_movement_s,
            "completion_pct": timing.completion_pct,
            "repetitions": rollup["repetitions"],
            "session_ids": rollup["session_ids"],
        })

    pct = round(min(engaged / planned, 4.0) * 100, 1) if planned else 0.0
    if not blocks:
        state = "none"
    elif pct >= 100:
        state = "exceeded" if pct > 110 else "met"
    elif pct >= ADHERENCE_THRESHOLD * 100:
        state = "met"
    elif engaged > 0:
        state = "partial"
    else:
        state = "planned"

    return {
        "date": local_date,
        "state": state,
        "planned_s": planned,
        "engaged_s": round(engaged, 1),
        "active_movement_s": round(active, 1),
        "completion_pct": pct,
        "block_count": len(blocks),
        "completed_block_count": counted,
        "repetitions": reps,
        "exercises": sorted(set(exercises)),
        "entries": entries,
    }


def calendar(db: DbSession, patient_id: int, start_date: date, end_date: date, *, now=None) -> dict:
    """Bounded day-by-day adherence. The server aggregates; the browser draws."""
    blocks = in_range(db, patient_id, start_date.isoformat(), end_date.isoformat())
    by_date: dict[str, list[FocusSession]] = {}
    for focus in blocks:
        by_date.setdefault(focus.local_date, []).append(focus)

    days = []
    cursor = start_date
    today = (now or datetime.now(timezone.utc)).date()
    while cursor <= end_date:
        key = cursor.isoformat()
        summary = day_summary(by_date.get(key, []), key, now=now)
        if not by_date.get(key) and cursor > today:
            summary["state"] = "future"
        days.append(summary)
        cursor += timedelta(days=1)

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "adherence_threshold_pct": round(ADHERENCE_THRESHOLD * 100),
        "days": days,
    }


def streak(days: list[dict], *, today: str) -> dict:
    """Consecutive days meeting the stated threshold, counting back from today.

    Today only breaks the streak once it is over: a day still in progress is
    skipped rather than counted as a miss.
    """
    by_date = {d["date"]: d for d in days}
    current = 0
    cursor = date.fromisoformat(today)
    first = True
    while True:
        key = cursor.isoformat()
        day = by_date.get(key)
        if day is None:
            break
        if day["state"] in ("met", "exceeded"):
            current += 1
        elif first and day["state"] in ("partial", "planned", "none"):
            # Today is not finished yet; look at yesterday instead.
            pass
        else:
            break
        first = False
        cursor -= timedelta(days=1)

    best = 0
    run = 0
    for day in sorted(days, key=lambda d: d["date"]):
        if day["state"] in ("met", "exceeded"):
            run += 1
            best = max(best, run)
        elif day["state"] != "future":
            run = 0

    return {
        "current_days": current,
        "best_days": best,
        "threshold_pct": round(ADHERENCE_THRESHOLD * 100),
        "rule": (
            f"A day counts when at least {round(ADHERENCE_THRESHOLD * 100)}% of that day's "
            "planned minutes were actually worked."
        ),
    }


def analytics(days: list[dict], *, today: str) -> dict:
    """Rehabilitation-specific period summary. Server-side by design (§28)."""
    active_days = [d for d in days if d["block_count"] > 0]
    worked_days = [d for d in days if d["engaged_s"] > 0]
    planned_total = sum(d["planned_s"] for d in days)
    engaged_total = sum(d["engaged_s"] for d in days)
    movement_total = sum(d["active_movement_s"] for d in days)
    blocks = sum(d["block_count"] for d in days)
    completed = sum(d["completed_block_count"] for d in days)
    reps = sum(d["repetitions"] for d in days)

    starts = [e["start_minute"] for d in days for e in d["entries"] if e["start_minute"] is not None]
    exercises = Counter(x for d in days for x in d["exercises"])

    mean_start = round(sum(starts) / len(starts)) if starts else None
    return {
        "planned_minutes": round(planned_total / 60, 1),
        "completed_minutes": round(engaged_total / 60, 1),
        "active_movement_minutes": round(movement_total / 60, 1),
        "blocks_planned": blocks,
        "blocks_completed": completed,
        "days_with_a_plan": len(active_days),
        "days_worked": len(worked_days),
        "repetitions": reps,
        "goal_completion_rate_pct": (
            round(min(engaged_total / planned_total, 4.0) * 100, 1) if planned_total else None
        ),
        "mean_block_minutes": (
            round(engaged_total / 60 / blocks, 1) if blocks else None
        ),
        "mean_start_minute": mean_start,
        "most_common_exercise": exercises.most_common(1)[0][0] if exercises else None,
        "exercise_frequency": dict(exercises),
        "streak": streak(days, today=today),
    }


# --- reminders ------------------------------------------------------------ #

def next_occurrence(reminder: FocusReminder, *, now: datetime | None = None) -> datetime | None:
    """When this reminder would next be due.

    Reported so the interface can show a real next time. Nothing delivers it:
    this deployment has no push channel, and inventing a delivery event would
    make a missed reminder indistinguishable from a sent one.
    """
    if not reminder.enabled:
        return None
    days = reminder.weekday_list
    if not days:
        return None
    try:
        hh, mm = (int(x) for x in reminder.time_of_day.split(":"))
    except (ValueError, AttributeError):
        return None

    now = now or datetime.now(timezone.utc)
    for offset in range(0, 8):
        candidate_date = (now + timedelta(days=offset)).date()
        if candidate_date.weekday() not in days:
            continue
        candidate = datetime.combine(candidate_date, time(hh, mm), tzinfo=timezone.utc)
        if candidate > now:
            return candidate
    return None


def serialise_reminder(reminder: FocusReminder, *, now: datetime | None = None) -> dict:
    upcoming = next_occurrence(reminder, now=now)
    return {
        "id": reminder.id,
        "patient_id": reminder.patient_id,
        "time_of_day": reminder.time_of_day,
        "weekdays": reminder.weekday_list,
        "timezone_name": reminder.timezone_name,
        "target_duration_s": reminder.target_duration_s,
        "exercise_type": reminder.exercise_type.value,
        "enabled": reminder.enabled,
        "next_occurrence": _iso(upcoming),
        # Stated plainly rather than implied by a bell icon.
        "delivery": "NOT_CONFIGURED",
        "delivery_note": (
            "Reminder times are stored and shown in the workspace. This deployment "
            "has no push or email channel, so nothing is sent to a device."
        ),
    }
