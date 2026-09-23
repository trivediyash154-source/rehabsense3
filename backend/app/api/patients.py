"""Patient endpoints.

Preserves the documented contract:
    POST /api/patients, GET /api/patients, GET /api/patients/{id}

Clinician-only fields are served through a separate schema, chosen by role —
the backend never returns notes to a patient and relies on the UI to hide them.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbDep
from app.schemas.common import Page
from app.schemas.patient import PatientClinical, PatientCreate, PatientPublic, PatientUpdate
from app.services import authz, patient_service

router = APIRouter(prefix="/patients", tags=["patients"])


def _serialise(db, user, patient):
    if authz.can_view_clinical_detail(db, user, patient):
        return PatientClinical.model_validate(patient)
    return PatientPublic.model_validate(patient)


@router.post("", response_model=PatientClinical, status_code=status.HTTP_201_CREATED)
def create_patient(payload: PatientCreate, user: CurrentUser, db: DbDep):
    authz.require_clinician(user)
    patient = patient_service.create_patient(db, payload, user)
    db.commit()
    db.refresh(patient)
    return PatientClinical.model_validate(patient)


# response_model is intentionally omitted: the handler chooses
# PatientPublic or PatientClinical by role, and declaring the wider
# schema here would re-introduce the clinician fields as nulls.
@router.get("", response_model=None)
def list_patients(
    user: CurrentUser,
    db: DbDep,
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    allowed = authz.visible_patient_ids(db, user)
    rows, total = patient_service.list_patients(
        db, allowed_ids=allowed, search=search, limit=limit, offset=offset
    )
    return {
        "items": [_serialise(db, user, p).model_dump(mode="json") for p in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.get("/roster", response_model=None)
def patient_roster(user: CurrentUser, db: DbDep):
    """Every patient this caller may see, with a compact movement summary.

    Declared before /{patient_id} so "roster" is not parsed as an id.
    """
    from app.services.progress_service import build_roster

    allowed = authz.visible_patient_ids(db, user)
    patients = patient_service.list_for_ids(db, allowed)
    return {"items": build_roster(db, patients), "total": len(patients)}


@router.get("/{patient_id}", response_model=None)
def get_patient(patient_id: int, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, patient_id)
    return _serialise(db, user, patient)


@router.patch("/{patient_id}", response_model=PatientClinical)
def update_patient(patient_id: int, payload: PatientUpdate, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, patient_id)
    if not authz.can_edit_patient(db, user, patient):
        from app.core.exceptions import Forbidden

        raise Forbidden("Only an assigned clinician may edit this record.")
    patient_service.update_patient(db, patient, payload, user)
    db.commit()
    db.refresh(patient)
    return PatientClinical.model_validate(patient)
