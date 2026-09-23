"""Recovery Focus: planned rehabilitation blocks and adherence.

Focus wraps the existing session pipeline rather than replacing it, so every
movement figure returned here was produced by the analytics layer and stored
on a `Session`. This module contributes the plan, the clock and the adherence
arithmetic, and nothing else.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from app.core.exceptions import Conflict, Forbidden, SessionNotFound
from app.db.models.audit import AuditAction
from app.db.models.focus import FocusReminder, FocusSession, FocusStatus
from app.db.models.session import Session as SessionModel
from app.schemas.focus import (
    FocusCreate,
    FocusSessionLink,
    FocusUpdate,
    ReminderCreate,
    ReminderUpdate,
)
from app.services import audit_service, authz, focus_service

router = APIRouter(prefix="/focus", tags=["focus"])

# A calendar request is bounded so a long-running account cannot be asked to
# serialise years of history into one response.
MAX_RANGE_DAYS = 400


def _authorised(db, user, focus_id: int) -> FocusSession:
    """A block the caller may see, reported as missing when they may not."""
    focus = focus_service.get(db, focus_id)
    patient = authz.get_patient_or_403(db, user, focus.patient_id)
    if patient is None:  # pragma: no cover - get_patient_or_403 raises first
        raise focus_service.FocusNotFound()
    return focus


def _editable(db, user, focus_id: int) -> FocusSession:
    focus = _authorised(db, user, focus_id)
    if not authz.can_edit_patient(db, user, focus.patient):
        raise Forbidden("Only an assigned clinician or the patient may change this block.")
    return focus


def _local_today(user, request_date: str | None) -> str:
    """The caller's own calendar day.

    A patient exercising at 8pm in UTC+05:30 is on tomorrow's UTC date, so a
    UTC "today" would file the session on the wrong day and report an empty
    one. The client sends its local date; when it does not, fall back to the
    account's stored timezone rather than guessing UTC.
    """
    if request_date:
        return request_date
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(getattr(user, "timezone", None) or "UTC")
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).date().isoformat()


# --- blocks --------------------------------------------------------------- #

@router.post("", status_code=status.HTTP_201_CREATED)
def create_focus(payload: FocusCreate, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, payload.patient_id)
    if not authz.can_edit_patient(db, user, patient):
        raise Forbidden("Only an assigned clinician or the patient may plan a block.")

    focus = focus_service.create(
        db,
        patient_id=patient.id,
        actor_id=user.id,
        target_duration_s=payload.target_duration_s,
        exercise_type=payload.exercise_type,
        local_date=payload.local_date,
        scheduled_for=payload.scheduled_for,
        notes=payload.notes,
    )
    audit_service.record(
        db, action=AuditAction.SESSION_STARTED, entity_type="focus_session",
        entity_id=focus.id, actor_id=user.id,
    )
    db.commit()
    return focus_service.serialise(focus_service.get(db, focus.id))


@router.get("/today")
def today(
    user: CurrentUser,
    db: DbDep,
    patient_id: int = Query(...),
    local_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """Everything the Focus panel needs for one day, in one request."""
    patient = authz.get_patient_or_403(db, user, patient_id)
    # Close anything abandoned before reporting, so a stale block cannot show
    # as running for hours.
    if focus_service.reap_stale(db, patient.id):
        db.commit()

    day = _local_today(user, local_date)
    blocks = focus_service.for_date(db, patient.id, day)
    summary = focus_service.day_summary(blocks, day)

    active = next(
        (b for b in blocks if b.status in (FocusStatus.ACTIVE, FocusStatus.PAUSED)), None
    )
    reminders = db.execute(
        select(FocusReminder).where(
            FocusReminder.patient_id == patient.id, FocusReminder.enabled.is_(True)
        )
    ).scalars()

    return {
        "patient_id": patient.id,
        "local_date": day,
        "summary": summary,
        "blocks": [focus_service.serialise(b) for b in blocks],
        "active_block": focus_service.serialise(active) if active else None,
        "reminders": [focus_service.serialise_reminder(r) for r in reminders],
        "presets_s": focus_service.PRESET_DURATIONS_S,
        "adherence_threshold_pct": round(focus_service.ADHERENCE_THRESHOLD * 100),
    }


@router.get("/calendar")
def calendar(
    user: CurrentUser,
    db: DbDep,
    patient_id: int = Query(...),
    start: date = Query(...),
    end: date = Query(...),
):
    patient = authz.get_patient_or_403(db, user, patient_id)
    if end < start:
        raise Conflict("The end date must not precede the start date.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise Conflict(f"Ask for at most {MAX_RANGE_DAYS} days at a time.")

    grid = focus_service.calendar(db, patient.id, start, end)
    grid["analytics"] = focus_service.analytics(grid["days"], today=_local_today(user, None))
    return grid


@router.get("/history")
def history(
    user: CurrentUser,
    db: DbDep,
    patient_id: int = Query(...),
    period: str = Query(default="week", pattern="^(today|week|month|custom)$"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    patient = authz.get_patient_or_403(db, user, patient_id)
    today_d = date.fromisoformat(_local_today(user, None))

    if period == "today":
        start_d, end_d = today_d, today_d
    elif period == "week":
        start_d, end_d = today_d - timedelta(days=6), today_d
    elif period == "month":
        start_d, end_d = today_d - timedelta(days=29), today_d
    else:
        if not start or not end:
            raise Conflict("A custom period needs both start and end dates.")
        start_d, end_d = start, end
        if (end_d - start_d).days > MAX_RANGE_DAYS:
            raise Conflict(f"Ask for at most {MAX_RANGE_DAYS} days at a time.")

    grid = focus_service.calendar(db, patient.id, start_d, end_d)
    return {
        "period": period,
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat(),
        "days": grid["days"],
        "analytics": focus_service.analytics(grid["days"], today=today_d.isoformat()),
    }


@router.get("/{focus_id}")
def get_focus(focus_id: int, user: CurrentUser, db: DbDep):
    return focus_service.serialise(_authorised(db, user, focus_id))


@router.patch("/{focus_id}")
def update_focus(focus_id: int, payload: FocusUpdate, user: CurrentUser, db: DbDep):
    focus = _editable(db, user, focus_id)
    if focus.status not in (FocusStatus.READY, FocusStatus.PAUSED):
        raise Conflict("A running or finished block cannot be re-planned.")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(focus, field, value)
    db.commit()
    return focus_service.serialise(focus_service.get(db, focus_id))


# --- lifecycle ------------------------------------------------------------ #

def _transition(db, user, focus_id: int, fn):
    focus = _editable(db, user, focus_id)
    fn(db, focus)
    db.commit()
    return focus_service.serialise(focus_service.get(db, focus_id))


@router.post("/{focus_id}/start")
def start_focus(focus_id: int, user: CurrentUser, db: DbDep):
    return _transition(db, user, focus_id, focus_service.start)


@router.post("/{focus_id}/pause")
def pause_focus(focus_id: int, user: CurrentUser, db: DbDep):
    return _transition(db, user, focus_id, focus_service.pause)


@router.post("/{focus_id}/resume")
def resume_focus(focus_id: int, user: CurrentUser, db: DbDep):
    return _transition(db, user, focus_id, focus_service.resume)


@router.post("/{focus_id}/complete")
def complete_focus(focus_id: int, user: CurrentUser, db: DbDep):
    result = _transition(db, user, focus_id, focus_service.complete)
    audit_service.record(
        db, action=AuditAction.SESSION_ENDED, entity_type="focus_session",
        entity_id=focus_id, actor_id=user.id,
    )
    db.commit()
    return result


@router.post("/{focus_id}/cancel")
def cancel_focus(focus_id: int, user: CurrentUser, db: DbDep):
    return _transition(db, user, focus_id, focus_service.cancel)


@router.post("/{focus_id}/sessions")
def link_session(focus_id: int, payload: FocusSessionLink, user: CurrentUser, db: DbDep):
    """Attach a rehabilitation session to this block.

    The session keeps owning its own analytics; the block only records that
    the work happened inside it.
    """
    focus = _editable(db, user, focus_id)
    session = db.get(SessionModel, payload.session_id)
    if session is None or session.patient_id != focus.patient_id:
        # Same shape as every other unauthorised lookup: not confirmed to exist.
        raise SessionNotFound()
    session.focus_id = focus.id
    db.commit()
    return focus_service.serialise(focus_service.get(db, focus_id))


# --- reminders ------------------------------------------------------------ #

@router.get("/reminders/list")
def list_reminders(user: CurrentUser, db: DbDep, patient_id: int = Query(...)):
    patient = authz.get_patient_or_403(db, user, patient_id)
    rows = db.execute(
        select(FocusReminder).where(FocusReminder.patient_id == patient.id)
        .order_by(FocusReminder.time_of_day)
    ).scalars()
    return {"items": [focus_service.serialise_reminder(r) for r in rows]}


@router.post("/reminders", status_code=status.HTTP_201_CREATED)
def create_reminder(payload: ReminderCreate, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, payload.patient_id)
    if not authz.can_edit_patient(db, user, patient):
        raise Forbidden("Only an assigned clinician or the patient may set reminders.")
    reminder = FocusReminder(
        patient_id=patient.id,
        created_by=user.id,
        time_of_day=payload.time_of_day,
        weekdays=",".join(str(d) for d in payload.weekdays),
        timezone_name=payload.timezone_name,
        target_duration_s=payload.target_duration_s,
        exercise_type=payload.exercise_type,
        enabled=payload.enabled,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return focus_service.serialise_reminder(reminder)


@router.patch("/reminders/{reminder_id}")
def update_reminder(reminder_id: int, payload: ReminderUpdate, user: CurrentUser, db: DbDep):
    reminder = db.get(FocusReminder, reminder_id)
    if reminder is None:
        raise focus_service.FocusNotFound()
    patient = authz.get_patient_or_403(db, user, reminder.patient_id)
    if not authz.can_edit_patient(db, user, patient):
        raise Forbidden("Only an assigned clinician or the patient may change reminders.")

    data = payload.model_dump(exclude_unset=True)
    if "weekdays" in data and data["weekdays"] is not None:
        reminder.weekdays = ",".join(str(d) for d in data.pop("weekdays"))
    for field, value in data.items():
        if value is not None:
            setattr(reminder, field, value)
    db.commit()
    db.refresh(reminder)
    return focus_service.serialise_reminder(reminder)


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(reminder_id: int, user: CurrentUser, db: DbDep) -> None:
    reminder = db.get(FocusReminder, reminder_id)
    if reminder is None:
        raise focus_service.FocusNotFound()
    patient = authz.get_patient_or_403(db, user, reminder.patient_id)
    if not authz.can_edit_patient(db, user, patient):
        raise Forbidden("Only an assigned clinician or the patient may remove reminders.")
    db.delete(reminder)
    db.commit()
