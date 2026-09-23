"""Development-only data generation.

Creating a believable workspace has to go through the real pipeline, not an
INSERT. This endpoint drives the same simulator a developer runs from a
terminal -- which speaks the production ingestion protocol -- so every
session it produces was calibrated, fused, segmented and scored by the
analytics layer exactly as hardware data would be.

The route is unavailable when DEBUG is off, because starting OS processes on
request is a development affordance, not a product feature.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbDep
from app.core.config import get_settings
from app.core.exceptions import AppError, Conflict
from app.core.logging import get_logger, log_event
from app.db.models.patient import AssignmentStatus, Leg, PatientAssignment, PatientProfile
from app.db.models.session import (
    ExerciseType,
    MetricSnapshot,
    RepEvent,
    RiskFlag,
    Session as SessionModel,
    SessionStatus,
)
from app.schemas.dev import SeedRequest
from app.services import report_service, session_service
from app.services.live_registry import registry

router = APIRouter(prefix="/dev", tags=["dev"])
logger = get_logger("rehabsense.dev")


class DevDisabled(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    detail = "Not Found"


def _require_dev() -> None:
    if not get_settings().debug:
        raise DevDisabled()


# SINGLE_LEG_BALANCE is deliberately absent. The recovery indicator weights
# range of motion (0.30) and cadence (0.15), so a static hold scores around
# 31 however well it is performed -- a scoring artefact, not a recovery
# signal, and it reads as a crash in the trend line. Only repetition-based
# exercises belong in a seeded history.
#
# Each entry is one session: a scenario the simulator understands, how long to
# stream, and how many days back to date it. Together they form a longitudinal
# story rather than five copies of the same session.
PROFILES: dict[str, list[dict]] = {
    # A twelve-week arc: marked asymmetry at referral, steadily closing.
    "improving": [
        {"scenario": "SEVERE_ASYMMETRY", "duration": 35, "days_ago": 84, "pain": 7, "exercise": "SIT_TO_STAND",
         "note": "Baseline assessment. Marked asymmetry on the operated side."},
        {"scenario": "SEVERE_ASYMMETRY", "duration": 35, "days_ago": 77, "pain": 7, "exercise": "KNEE_EXTENSION",
         "note": "Range work only. Operated limb guarding throughout."},
        {"scenario": "SEVERE_ASYMMETRY", "duration": 40, "days_ago": 70, "pain": 6, "exercise": "SIT_TO_STAND",
         "note": "Tolerating a longer session. Range still restricted."},
        {"scenario": "ASYMMETRY", "duration": 40, "days_ago": 63, "pain": 6, "exercise": "WALK",
         "note": "First walking assessment. Stance time uneven."},
        {"scenario": "ASYMMETRY", "duration": 45, "days_ago": 56, "pain": 5, "exercise": "SQUAT",
         "note": "Loaded movement introduced. Depth limited by the operated side."},
        {"scenario": "ASYMMETRY", "duration": 45, "days_ago": 49, "pain": 5, "exercise": "WALK",
         "note": "Walking analysis. Operated limb still guarding."},
        {"scenario": "ASYMMETRY", "duration": 50, "days_ago": 42, "pain": 4, "exercise": "STEP_UP",
         "note": "Step-up added. Control better than expected."},
        {"scenario": "RECOVERY_STABLE", "duration": 50, "days_ago": 35, "pain": 4, "exercise": "SQUAT",
         "note": "Guided exercise session. Range beginning to open."},
        {"scenario": "RECOVERY_STABLE", "duration": 55, "days_ago": 28, "pain": 3, "exercise": "WALK",
         "note": "Cadence steadier across the whole recording."},
        {"scenario": "IMPROVING", "duration": 55, "days_ago": 21, "pain": 3, "exercise": "STEP_UP",
         "note": "Bilateral movement review. Symmetry noticeably closer."},
        {"scenario": "IMPROVING", "duration": 60, "days_ago": 14, "pain": 2, "exercise": "SQUAT",
         "note": "Depth close to matched between limbs."},
        {"scenario": "IMPROVING", "duration": 60, "days_ago": 7, "pain": 2, "exercise": "STEP_UP",
         "note": "Step-up control matched between limbs."},
        {"scenario": "IMPROVING", "duration": 60, "days_ago": 0, "pain": 1, "exercise": "WALK",
         "note": "Latest session. Most consistent recording so far."},
    ],
    # Consistent performer: the interesting question is what stays steady.
    "stable": [
        {"scenario": "RECOVERY_STABLE", "duration": 45, "days_ago": 77, "pain": 3, "exercise": "WALK",
         "note": "Steady baseline, good bilateral coverage."},
        {"scenario": "RECOVERY_STABLE", "duration": 45, "days_ago": 70, "pain": 3, "exercise": "SQUAT",
         "note": "Consistent with the previous session."},
        {"scenario": "IMPROVING", "duration": 50, "days_ago": 63, "pain": 3, "exercise": "STEP_UP",
         "note": "Range a little wider than the baseline."},
        {"scenario": "RECOVERY_STABLE", "duration": 50, "days_ago": 56, "pain": 2, "exercise": "WALK",
         "note": "Cadence held across the full recording."},
        {"scenario": "RECOVERY_STABLE", "duration": 50, "days_ago": 49, "pain": 2, "exercise": "SIT_TO_STAND",
         "note": "Repetition count up without loss of control."},
        {"scenario": "IMPROVING", "duration": 55, "days_ago": 42, "pain": 2, "exercise": "SQUAT",
         "note": "Cadence a little higher than usual."},
        {"scenario": "RECOVERY_STABLE", "duration": 55, "days_ago": 35, "pain": 2, "exercise": "WALK",
         "note": "No change requiring review."},
        {"scenario": "IMPROVING", "duration": 55, "days_ago": 28, "pain": 2, "exercise": "SIT_TO_STAND",
         "note": "Transfers steady and even on both sides."},
        {"scenario": "RECOVERY_STABLE", "duration": 55, "days_ago": 21, "pain": 2, "exercise": "STEP_UP",
         "note": "Consistent with the last four sessions."},
        {"scenario": "IMPROVING", "duration": 60, "days_ago": 14, "pain": 1, "exercise": "SQUAT",
         "note": "Best symmetry recorded in this period."},
        {"scenario": "RECOVERY_STABLE", "duration": 60, "days_ago": 7, "pain": 1, "exercise": "WALK",
         "note": "Stable. No change requiring review."},
        {"scenario": "IMPROVING", "duration": 60, "days_ago": 0, "pain": 1, "exercise": "WALK",
         "note": "Latest session. Holding the gains."},
    ],
    # Recently referred: fewer sessions, and that itself is the story.
    "early": [
        {"scenario": "SEVERE_ASYMMETRY", "duration": 30, "days_ago": 35, "pain": 8, "exercise": "KNEE_EXTENSION",
         "note": "First recorded session after referral. Range clearly limited."},
        {"scenario": "SEVERE_ASYMMETRY", "duration": 30, "days_ago": 28, "pain": 7, "exercise": "KNEE_EXTENSION",
         "note": "Second session. Tolerating a little more movement."},
        {"scenario": "SEVERE_ASYMMETRY", "duration": 35, "days_ago": 21, "pain": 7, "exercise": "SIT_TO_STAND",
         "note": "Transfers introduced. Heavily favouring the unaffected side."},
        {"scenario": "SEVERE_ASYMMETRY", "duration": 35, "days_ago": 17, "pain": 6, "exercise": "SIT_TO_STAND",
         "note": "Slightly more even loading than last time."},
        {"scenario": "ASYMMETRY", "duration": 40, "days_ago": 12, "pain": 6, "exercise": "WALK",
         "note": "First walking recording. Short stance on the operated side."},
        {"scenario": "ASYMMETRY", "duration": 40, "days_ago": 8, "pain": 5, "exercise": "KNEE_EXTENSION",
         "note": "Range opening; symmetry still well below the unaffected side."},
        {"scenario": "ASYMMETRY", "duration": 45, "days_ago": 4, "pain": 5, "exercise": "WALK",
         "note": "Walking longer without a rest break."},
        {"scenario": "ASYMMETRY", "duration": 45, "days_ago": 0, "pain": 4, "exercise": "SIT_TO_STAND",
         "note": "Latest session. Trending in the right direction."},
    ],
    # Progress that flattens out -- a realistic pattern worth discussing.
    "plateau": [
        {"scenario": "ASYMMETRY", "duration": 40, "days_ago": 84, "pain": 5, "exercise": "SIT_TO_STAND",
         "note": "Baseline for this period."},
        {"scenario": "ASYMMETRY", "duration": 45, "days_ago": 77, "pain": 5, "exercise": "WALK",
         "note": "Early walking assessment."},
        {"scenario": "ASYMMETRY", "duration": 45, "days_ago": 70, "pain": 4, "exercise": "SQUAT",
         "note": "Range improving session on session."},
        {"scenario": "IMPROVING", "duration": 50, "days_ago": 63, "pain": 4, "exercise": "WALK",
         "note": "Clear improvement over baseline."},
        {"scenario": "IMPROVING", "duration": 50, "days_ago": 56, "pain": 3, "exercise": "STEP_UP",
         "note": "Best session of the period so far."},
        {"scenario": "RECOVERY_STABLE", "duration": 55, "days_ago": 49, "pain": 3, "exercise": "SQUAT",
         "note": "Held steady rather than improving further."},
        {"scenario": "RECOVERY_STABLE", "duration": 55, "days_ago": 42, "pain": 3, "exercise": "WALK",
         "note": "Similar to the previous session; progress has flattened."},
        {"scenario": "RECOVERY_STABLE", "duration": 55, "days_ago": 35, "pain": 3, "exercise": "SIT_TO_STAND",
         "note": "No measurable change over three weeks."},
        {"scenario": "RECOVERY_STABLE", "duration": 50, "days_ago": 28, "pain": 3, "exercise": "STEP_UP",
         "note": "Plateau continuing. Worth a conversation about load."},
        {"scenario": "RECOVERY_STABLE", "duration": 50, "days_ago": 21, "pain": 3, "exercise": "WALK",
         "note": "Stable, unchanged."},
        {"scenario": "IMPROVING", "duration": 55, "days_ago": 10, "pain": 2, "exercise": "SQUAT",
         "note": "First movement off the plateau after a programme change."},
        {"scenario": "IMPROVING", "duration": 55, "days_ago": 0, "pain": 2, "exercise": "WALK",
         "note": "Second consecutive session above the plateau."},
    ],
    # Inconsistent recordings: signal quality and risk flags interleaved.
    "variable": [
        {"scenario": "ASYMMETRY", "duration": 40, "days_ago": 80, "pain": 5, "exercise": "WALK",
         "note": "Baseline recording for this period."},
        {"scenario": "LOW_CONFIDENCE", "duration": 40, "days_ago": 73, "pain": 5, "exercise": "SQUAT",
         "note": "Signal quality reduced for part of the recording."},
        {"scenario": "ASYMMETRY", "duration": 45, "days_ago": 66, "pain": 5, "exercise": "WALK",
         "note": "Clean recording. Comparable with the baseline."},
        {"scenario": "RISK_EVENT", "duration": 45, "days_ago": 59, "pain": 6, "exercise": "STEP_UP",
         "note": "Range dropped through the session; flagged for review."},
        {"scenario": "RECOVERY_STABLE", "duration": 45, "days_ago": 52, "pain": 4, "exercise": "SIT_TO_STAND",
         "note": "Recovered to the expected range."},
        {"scenario": "SENSOR_DROP", "duration": 40, "days_ago": 45, "pain": 4, "exercise": "WALK",
         "note": "One node dropped out partway through."},
        {"scenario": "RECOVERY_STABLE", "duration": 50, "days_ago": 38, "pain": 4, "exercise": "SQUAT",
         "note": "Straps re-fitted; coverage back to full."},
        {"scenario": "LOW_CONFIDENCE", "duration": 45, "days_ago": 31, "pain": 4, "exercise": "STEP_UP",
         "note": "Step-up; signal confidence low on the operated side."},
        {"scenario": "IMPROVING", "duration": 50, "days_ago": 24, "pain": 3, "exercise": "WALK",
         "note": "Strongest walking recording so far."},
        {"scenario": "RISK_EVENT", "duration": 45, "days_ago": 17, "pain": 5, "exercise": "STEP_UP",
         "note": "Range declined again late in the session."},
        {"scenario": "RECOVERY_STABLE", "duration": 50, "days_ago": 9, "pain": 4, "exercise": "SQUAT",
         "note": "Back within the expected band."},
        {"scenario": "IMPROVING", "duration": 55, "days_ago": 0, "pain": 3, "exercise": "WALK",
         "note": "Cleanest recording in this period."},
    ],
}


def _run_simulator(session_id: int, host: str, *, scenario: str, leg: str,
                   exercise: str, duration: int, seed: int,
                   speed: float = 1.0) -> subprocess.CompletedProcess:
    """Stream one session through the production ingestion socket.

    Runs to completion and returns the process result so a failure surfaces
    instead of silently producing an empty session.
    """
    return subprocess.run(
        [sys.executable, "-m", "app.simulator.sensor_simulator",
         "--session-id", str(session_id), "--host", host, "--exercise", exercise,
         "--operated-leg", leg, "--scenario", scenario, "--seed", str(seed),
         "--fsr", "--duration", str(duration), "--speed", str(speed)],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True, text=True, timeout=duration + 90,
    )


@router.post("/demo-data")
async def generate_demo_data(payload: SeedRequest, request: Request, user: CurrentUser, db: DbDep):
    """Create patients and stream real sessions for the signed-in account.

    Everything produced here is recorded with `mode=SIMULATED`, so the
    workspace labels it as a simulated stream rather than implying a device
    was attached.
    """
    _require_dev()
    host = f"{request.url.hostname}:{request.url.port or 8000}"
    started = time.perf_counter()

    plan = [
        ("Yash Trivedi", Leg.RIGHT, "improving"),
        ("Priya Nair", Leg.LEFT, "stable"),
        ("Rohan Iyer", Leg.LEFT, "variable"),
        ("Ananya Desai", Leg.RIGHT, "early"),
        ("Kabir Menon", Leg.LEFT, "plateau"),
    ][: max(1, min(payload.patients, 5))]

    created = {"patients": [], "sessions": 0, "reps": 0, "risks": 0, "metrics": 0}
    failures: list[dict] = []
    seed = int(time.time()) % 9000

    for name, leg, profile_key in plan:
        existing = db.execute(
            select(PatientProfile).join(
                PatientAssignment, PatientAssignment.patient_id == PatientProfile.id
            ).where(
                PatientAssignment.clinician_id == user.id,
                PatientAssignment.status == AssignmentStatus.ACTIVE,
                PatientProfile.name == name,
            )
        ).scalars().first()

        if existing is not None and not payload.force:
            created["patients"].append({"id": existing.id, "name": name, "reused": True})
            continue

        patient = PatientProfile(
            name=name,
            operated_leg=leg,
            age=24 + (seed % 12),
            surgery_date=(datetime.now(timezone.utc) - timedelta(days=90)).date(),
            notes="Illustrative demo record generated through the sensor simulator.",
        )
        db.add(patient)
        db.flush()
        db.add(PatientAssignment(
            patient_id=patient.id, clinician_id=user.id, status=AssignmentStatus.ACTIVE,
        ))
        db.commit()

        for entry in PROFILES[profile_key]:
            seed += 1
            session = SessionModel(
                patient_id=patient.id,
                created_by=user.id,
                exercise_type=ExerciseType(entry.get("exercise", payload.exercise.value)),
                status=SessionStatus.ACTIVE,
                started_at=datetime.now(timezone.utc),
            )
            db.add(session)
            db.commit()
            db.refresh(session)

            # Off the event loop: the simulator connects back to *this*
            # server's ingestion socket, so blocking here would deadlock --
            # the server could never accept the connection it is waiting for.
            result = await asyncio.to_thread(
                _run_simulator,
                session.id, host, scenario=entry["scenario"], leg=leg.value,
                exercise=entry.get("exercise", payload.exercise.value),
                duration=entry["duration"], seed=seed, speed=payload.speed,
            )
            if result.returncode != 0:
                failures.append({
                    "session_id": session.id,
                    "scenario": entry["scenario"],
                    "stderr": (result.stderr or "")[-300:],
                })

            # Finalise through the same path the API uses, so the stored
            # summary is the live processor's, not a second calculation.
            summary = await registry.finalize(session.id, entry["pain"])
            if summary is None:
                summary = report_service.summary_from_persisted(db, session)
            session_service.end_session(
                db, session, summary=summary, reported_pain=entry["pain"],
                notes=entry["note"], actor=user,
            )
            db.commit()
            await registry.close(session.id)

            # Backdate so the history forms a real timeline. Only the
            # timestamps move; every metric stays exactly as computed.
            db.refresh(session)
            if entry["days_ago"] > 0 and session.ended_at is not None:
                shift = timedelta(days=entry["days_ago"])
                session.started_at = session.started_at - shift
                session.ended_at = session.ended_at - shift
                for snapshot in session.metrics:
                    snapshot.ts = snapshot.ts - shift
                for rep in session.reps:
                    rep.ts = rep.ts - shift
                for flag in session.risk_flags:
                    flag.ts = flag.ts - shift
            session.notes = entry["note"]
            db.commit()

            # Counted from the database rather than from a possibly-stale
            # relationship on the session object.
            created["sessions"] += 1
            created["reps"] += db.execute(
                select(func.count()).select_from(RepEvent).where(RepEvent.session_id == session.id)
            ).scalar_one()
            created["risks"] += db.execute(
                select(func.count()).select_from(RiskFlag).where(RiskFlag.session_id == session.id)
            ).scalar_one()
            created["metrics"] += db.execute(
                select(func.count()).select_from(MetricSnapshot).where(MetricSnapshot.session_id == session.id)
            ).scalar_one()

        created["patients"].append({"id": patient.id, "name": name, "reused": False})

    log_event(logger, "demo_data_generated", actor_id=user.id, **{
        k: v for k, v in created.items() if k != "patients"
    })
    return {
        **created,
        "failures": failures,
        "patient_count": len(created["patients"]),
        "elapsed_s": round(time.perf_counter() - started, 1),
        "source": "SIMULATED",
        "note": (
            "Every session above was streamed through the production ingestion "
            "socket by the sensor simulator and scored by the analytics layer. "
            "No device was attached and no value was inserted directly."
        ),
    }
