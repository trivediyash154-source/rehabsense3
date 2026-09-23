"""Recovery Focus: planning, derived timing, adherence and ownership.

The timing tests drive the service directly with explicit timestamps, because
the point of the design is that durations are *derived* from a ledger. If a
counter ever creeps back in, these fail.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.focus import FocusEventKind, FocusStatus
from app.db.models.session import ExerciseType
from app.services import focus_service

T0 = datetime(2026, 9, 8, 18, 30, tzinfo=timezone.utc)


def _block(db, patient_id, *, target_s=1800, on="2026-09-08"):
    focus = focus_service.create(
        db, patient_id=patient_id, actor_id=None, target_duration_s=target_s,
        exercise_type=ExerciseType.WALK, local_date=on,
    )
    db.commit()
    return focus


# --- derived timing ------------------------------------------------------- #

@pytest.mark.parametrize("minutes", [5, 25, 30, 60])
def test_a_block_runs_for_its_full_target(db, patient_record, minutes):
    """§29: verify the arithmetic at each offered target."""
    focus = _block(db, patient_record["id"], target_s=minutes * 60)
    focus_service.start(db, focus, now=T0)
    focus_service.complete(db, focus, now=T0 + timedelta(minutes=minutes))
    db.commit()

    timing = focus_service.compute_timing(focus)
    assert timing.elapsed_s == pytest.approx(minutes * 60)
    assert timing.paused_s == 0
    assert timing.engaged_s == pytest.approx(minutes * 60)
    assert timing.completion_pct == pytest.approx(100.0)


def test_ending_early_reports_the_real_duration(db, patient_record):
    """§8: 28:42 against a 30:00 target is 95.7%, not 100%."""
    focus = _block(db, patient_record["id"], target_s=1800)
    focus_service.start(db, focus, now=T0)
    focus_service.complete(db, focus, now=T0 + timedelta(minutes=28, seconds=42))
    db.commit()

    timing = focus_service.compute_timing(focus)
    assert timing.engaged_s == pytest.approx(1722.0)
    assert timing.completion_pct == pytest.approx(95.7, abs=0.05)


def test_paused_time_does_not_count_as_worked(db, patient_record):
    """§5: the plan is unchanged by a pause; engaged time stops."""
    focus = _block(db, patient_record["id"], target_s=1800)
    focus_service.start(db, focus, now=T0)
    focus_service.pause(db, focus, now=T0 + timedelta(minutes=10))
    focus_service.resume(db, focus, now=T0 + timedelta(minutes=15))
    focus_service.complete(db, focus, now=T0 + timedelta(minutes=35))
    db.commit()

    timing = focus_service.compute_timing(focus)
    assert timing.elapsed_s == pytest.approx(35 * 60)
    assert timing.paused_s == pytest.approx(5 * 60)
    assert timing.engaged_s == pytest.approx(30 * 60)
    assert timing.completion_pct == pytest.approx(100.0)
    assert timing.interruptions == 1
    assert focus.target_duration_s == 1800


def test_multiple_pauses_accumulate(db, patient_record):
    focus = _block(db, patient_record["id"], target_s=1800)
    focus_service.start(db, focus, now=T0)
    for i in range(3):
        focus_service.pause(db, focus, now=T0 + timedelta(minutes=5 + i * 10))
        focus_service.resume(db, focus, now=T0 + timedelta(minutes=7 + i * 10))
    focus_service.complete(db, focus, now=T0 + timedelta(minutes=40))
    db.commit()

    timing = focus_service.compute_timing(focus)
    assert timing.interruptions == 3
    assert timing.paused_s == pytest.approx(6 * 60)
    assert timing.engaged_s == pytest.approx(34 * 60)


def test_completing_while_paused_stops_the_pause_clock(db, patient_record):
    """Ending from a paused state must not keep accruing paused time."""
    focus = _block(db, patient_record["id"], target_s=1800)
    focus_service.start(db, focus, now=T0)
    focus_service.pause(db, focus, now=T0 + timedelta(minutes=20))
    focus_service.complete(db, focus, now=T0 + timedelta(minutes=25))
    db.commit()

    timing = focus_service.compute_timing(focus)
    assert timing.paused_s == pytest.approx(5 * 60)
    assert timing.engaged_s == pytest.approx(20 * 60)


def test_an_open_pause_freezes_engaged_time(db, patient_record):
    """§5: while paused, engaged time must not advance with the wall clock."""
    focus = _block(db, patient_record["id"], target_s=1800)
    focus_service.start(db, focus, now=T0)
    focus_service.pause(db, focus, now=T0 + timedelta(minutes=10))
    db.commit()

    a = focus_service.compute_timing(focus, now=T0 + timedelta(minutes=12))
    b = focus_service.compute_timing(focus, now=T0 + timedelta(minutes=40))
    assert a.engaged_s == pytest.approx(600)
    assert b.engaged_s == pytest.approx(600), "paused blocks must not keep earning time"
    assert b.paused_s == pytest.approx(30 * 60)


def test_timing_is_reconstructed_not_counted(db, patient_record):
    """§4/§21: the answer depends only on stored timestamps."""
    focus = _block(db, patient_record["id"], target_s=1800)
    focus_service.start(db, focus, now=T0)
    focus_service.pause(db, focus, now=T0 + timedelta(minutes=8))
    focus_service.resume(db, focus, now=T0 + timedelta(minutes=11))
    focus_service.complete(db, focus, now=T0 + timedelta(minutes=31))
    db.commit()

    first = focus_service.compute_timing(focus)
    db.expire_all()
    reloaded = focus_service.get(db, focus.id)
    second = focus_service.compute_timing(reloaded)
    assert first == second


def test_an_unstarted_block_has_no_time(db, patient_record):
    focus = _block(db, patient_record["id"])
    timing = focus_service.compute_timing(focus)
    assert timing.elapsed_s == 0 and timing.engaged_s == 0
    assert timing.completion_pct == 0


# --- lifecycle guards ----------------------------------------------------- #

def test_pause_requires_a_running_block(db, patient_record):
    focus = _block(db, patient_record["id"])
    with pytest.raises(Exception):
        focus_service.pause(db, focus, now=T0)


def test_a_finished_block_cannot_restart(db, patient_record):
    focus = _block(db, patient_record["id"])
    focus_service.start(db, focus, now=T0)
    focus_service.complete(db, focus, now=T0 + timedelta(minutes=5))
    db.commit()
    with pytest.raises(Exception):
        focus_service.start(db, focus, now=T0 + timedelta(minutes=6))


def test_cancelling_records_the_end(db, patient_record):
    focus = _block(db, patient_record["id"])
    focus_service.start(db, focus, now=T0)
    focus_service.cancel(db, focus, now=T0 + timedelta(minutes=3))
    db.commit()
    assert focus.status is FocusStatus.CANCELLED
    assert focus.ended_at is not None
    assert any(e.kind is FocusEventKind.CANCELLED for e in focus.events)


def test_an_abandoned_block_is_interrupted_not_completed(db, patient_record):
    """§13: an abandoned block must not silently earn a day's adherence."""
    focus = _block(db, patient_record["id"])
    focus_service.start(db, focus, now=T0)
    db.commit()
    closed = focus_service.reap_stale(db, patient_record["id"], now=T0 + timedelta(hours=9))
    db.commit()
    assert closed == 1
    assert focus.status is FocusStatus.INTERRUPTED


# --- adherence ------------------------------------------------------------ #

def test_day_summary_aggregates_multiple_blocks(db, patient_record):
    """§26: two sessions in one day sum, and the day reflects both."""
    a = _block(db, patient_record["id"], target_s=1800)
    focus_service.start(db, a, now=T0)
    focus_service.complete(db, a, now=T0 + timedelta(minutes=30))
    b = _block(db, patient_record["id"], target_s=1800)
    focus_service.start(db, b, now=T0 + timedelta(hours=3))
    focus_service.complete(db, b, now=T0 + timedelta(hours=3, minutes=31))
    db.commit()

    blocks = focus_service.for_date(db, patient_record["id"], "2026-09-08")
    summary = focus_service.day_summary(blocks, "2026-09-08")
    assert summary["block_count"] == 2
    assert summary["planned_s"] == 3600
    assert summary["engaged_s"] == pytest.approx(61 * 60)
    assert summary["state"] in ("met", "exceeded")
    assert len(summary["entries"]) == 2
    # §11: each entry knows when it happened.
    assert all(e["start_minute"] is not None for e in summary["entries"])


def test_a_short_session_is_partial_not_met(db, patient_record):
    """§13: three minutes against a thirty-minute target is not a rehab day."""
    focus = _block(db, patient_record["id"], target_s=1800)
    focus_service.start(db, focus, now=T0)
    focus_service.complete(db, focus, now=T0 + timedelta(minutes=3))
    db.commit()

    summary = focus_service.day_summary(
        focus_service.for_date(db, patient_record["id"], "2026-09-08"), "2026-09-08"
    )
    assert summary["state"] == "partial"
    assert summary["completion_pct"] == pytest.approx(10.0)


def test_a_day_with_no_plan_reads_as_none(db, patient_record):
    summary = focus_service.day_summary([], "2026-09-01")
    assert summary["state"] == "none"
    assert summary["block_count"] == 0
    assert summary["planned_s"] == 0


def test_streak_counts_only_days_meeting_the_threshold():
    days = [
        {"date": "2026-09-04", "state": "met", "block_count": 1, "engaged_s": 1800,
         "planned_s": 1800, "active_movement_s": 0, "repetitions": 0, "exercises": [],
         "entries": [], "completed_block_count": 1, "completion_pct": 100.0},
        {"date": "2026-09-05", "state": "partial", "block_count": 1, "engaged_s": 300,
         "planned_s": 1800, "active_movement_s": 0, "repetitions": 0, "exercises": [],
         "entries": [], "completed_block_count": 0, "completion_pct": 16.7},
        {"date": "2026-09-06", "state": "met", "block_count": 1, "engaged_s": 1800,
         "planned_s": 1800, "active_movement_s": 0, "repetitions": 0, "exercises": [],
         "entries": [], "completed_block_count": 1, "completion_pct": 100.0},
        {"date": "2026-09-07", "state": "met", "block_count": 1, "engaged_s": 1800,
         "planned_s": 1800, "active_movement_s": 0, "repetitions": 0, "exercises": [],
         "entries": [], "completed_block_count": 1, "completion_pct": 100.0},
    ]
    result = focus_service.streak(days, today="2026-09-07")
    assert result["current_days"] == 2, "the partial day on the 5th breaks the run"
    assert result["best_days"] == 2
    assert "80%" in result["rule"]


# --- the patient's own day ------------------------------------------------ #

def test_today_follows_the_accounts_timezone(client, clinician, patient_record):
    """§9/§16: a UTC "today" files an evening session on the wrong day.

    At 20:00 in UTC+05:30 the UTC date has already rolled over, so a block the
    patient just finished would appear on tomorrow and today would read empty.
    """
    from datetime import datetime, timezone as tz
    from zoneinfo import ZoneInfo

    # Move the account to a zone ahead of UTC, as the API's fallback reads it.
    me = client.patch("/api/me", json={"timezone": "Asia/Kolkata"},
                      headers=clinician["headers"])
    assert me.status_code == 200, me.text

    local_day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    utc_day = datetime.now(tz.utc).date().isoformat()

    created = client.post("/api/focus", json={
        "patient_id": patient_record["id"], "target_duration_s": 1800,
        "exercise_type": "WALK", "local_date": local_day,
    }, headers=clinician["headers"])
    assert created.status_code == 201, created.text

    # No explicit date: the API must resolve the account's day, not UTC's.
    body = client.get(f"/api/focus/today?patient_id={patient_record['id']}",
                      headers=clinician["headers"]).json()
    assert body["local_date"] == local_day
    assert len(body["blocks"]) == 1, (
        f"block filed on {local_day} was not found; UTC day is {utc_day}"
    )


def test_an_explicit_local_date_is_always_honoured(client, clinician, patient_record):
    client.post("/api/focus", json={
        "patient_id": patient_record["id"], "target_duration_s": 900,
        "exercise_type": "SQUAT", "local_date": "2026-03-14",
    }, headers=clinician["headers"])
    body = client.get(
        f"/api/focus/today?patient_id={patient_record['id']}&local_date=2026-03-14",
        headers=clinician["headers"],
    ).json()
    assert body["local_date"] == "2026-03-14"
    assert len(body["blocks"]) == 1
    assert body["blocks"][0]["exercise_type"] == "SQUAT"
