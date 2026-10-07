"""Hardware-v2 movement analytics for the workspace pages.

    GET /analytics/overview              cohort dashboard (records you may see)
    GET /analytics/patients              command-centre roster
    GET /analytics/patients/{id}         one record's longitudinal movement summary
    GET /analytics/sessions              completed v2 sessions with their indicators
    GET /analytics/exercises             per-exercise aggregates
    GET /analytics/research              dataset / model / movement / longitudinal

Read-only and computed from stored rows on every request (see
app/services/movement_analytics.py), so the pages change when the data does.
Visibility is the same server-side rule as every other route.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbDep
from app.core.exceptions import Forbidden
from app.services import authz, movement_analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def analytics_overview(user: CurrentUser, db: DbDep):
    return movement_analytics.overview(db, user)


@router.get("/patients")
def analytics_roster(user: CurrentUser, db: DbDep):
    return movement_analytics.roster(db, user)


@router.get("/patients/{patient_id}")
def analytics_patient(patient_id: int, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, patient_id)
    return movement_analytics.patient_movement(db, patient)


@router.get("/sessions")
def analytics_sessions(user: CurrentUser, db: DbDep,
                       patient_id: int | None = Query(default=None),
                       limit: int = Query(default=500, ge=1, le=2000)):
    return movement_analytics.session_rows(db, user, patient_id=patient_id, limit=limit)


@router.get("/exercises")
def analytics_exercises(user: CurrentUser, db: DbDep):
    return movement_analytics.exercises(db, user)


@router.get("/research")
def analytics_research(user: CurrentUser, db: DbDep):
    if not authz.is_clinician(user):
        raise Forbidden("Research analytics are available to clinician and admin accounts.")
    return movement_analytics.research(db, user)
