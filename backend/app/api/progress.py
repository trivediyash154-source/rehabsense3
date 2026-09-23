"""Product-level patient endpoints: overview, progress, comparison, passport."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbDep
from app.core.exceptions import AppError
from app.services import authz, progress_service

router = APIRouter(prefix="/patients", tags=["progress"])


def _dates(start: date | None, end: date | None):
    if start and end and start > end:
        raise AppError("start_date must not be after end_date")
    return start, end


@router.get("/{patient_id}/overview")
def overview(patient_id: int, user: CurrentUser, db: DbDep):
    """Everything the workspace overview needs, in one request."""
    patient = authz.get_patient_or_403(db, user, patient_id)
    progress = progress_service.build_progress(db, patient)
    latest = progress["latest"]
    payload = {
        "patient": {
            "id": patient.id, "name": patient.name,
            "operated_leg": patient.operated_leg.value,
        },
        "latest_session": latest,
        "baseline_session": progress["baseline"],
        "session_count": progress["session_count"],
        "trends": progress["trends"],
        "responsible_use": progress["responsible_use"],
    }
    if progress["session_count"] >= 1:
        payload["comparison"] = progress_service.compare(db, patient)
    return payload


@router.get("/{patient_id}/progress")
def progress(
    patient_id: int, user: CurrentUser, db: DbDep,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    patient = authz.get_patient_or_403(db, user, patient_id)
    start, end = _dates(start_date, end_date)
    return progress_service.build_progress(db, patient, start=start, end=end)


@router.get("/{patient_id}/progress/compare")
def compare(
    patient_id: int, user: CurrentUser, db: DbDep,
    baseline_session_id: int | None = Query(default=None),
    current_session_id: int | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    patient = authz.get_patient_or_403(db, user, patient_id)
    start, end = _dates(start_date, end_date)
    return progress_service.compare(
        db, patient,
        baseline_session_id=baseline_session_id,
        current_session_id=current_session_id,
        start=start, end=end,
    )


@router.get("/{patient_id}/timeline")
def timeline(patient_id: int, user: CurrentUser, db: DbDep):
    """Time-normalised session briefs for the Movement Time Machine."""
    patient = authz.get_patient_or_403(db, user, patient_id)
    progress = progress_service.build_progress(db, patient)
    return {
        "patient_id": patient.id,
        "sessions": progress["sessions"],
        "milestones": progress["milestones"],
        "responsible_use": progress["responsible_use"],
    }


@router.get("/{patient_id}/passport")
def passport(patient_id: int, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, patient_id)
    return progress_service.build_passport(db, patient)
