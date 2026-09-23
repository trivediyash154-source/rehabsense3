"""Server-side authorisation.

Every rule here is enforced against the database. A role claim in a token is
necessary but never sufficient: a physiotherapist must additionally hold an
ACTIVE assignment to the patient in question.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.exceptions import Forbidden, PatientNotFound, SessionNotFound
from app.db.models.patient import AssignmentStatus, PatientAssignment, PatientProfile
from app.db.models.user import Role, User


def is_admin(user: User) -> bool:
    return user.role is Role.ADMIN


def is_clinician(user: User) -> bool:
    return user.role in (Role.PHYSIOTHERAPIST, Role.ADMIN)


def clinician_assigned(db: DbSession, clinician_id: int, patient_id: int) -> bool:
    stmt = select(PatientAssignment.id).where(
        PatientAssignment.clinician_id == clinician_id,
        PatientAssignment.patient_id == patient_id,
        PatientAssignment.status == AssignmentStatus.ACTIVE,
    )
    return db.execute(stmt).first() is not None


def owns_patient(db: DbSession, user: User, patient: PatientProfile) -> bool:
    return patient.user_id is not None and patient.user_id == user.id


def can_view_patient(db: DbSession, user: User, patient: PatientProfile) -> bool:
    if is_admin(user):
        return True
    if user.role is Role.PATIENT:
        return owns_patient(db, user, patient)
    if user.role is Role.PHYSIOTHERAPIST:
        return clinician_assigned(db, user.id, patient.id)
    if user.role is Role.TECHNICIAN:
        # Technicians work on devices, not patient records.
        return False
    return False


def can_edit_patient(db: DbSession, user: User, patient: PatientProfile) -> bool:
    if is_admin(user):
        return True
    if user.role is Role.PHYSIOTHERAPIST:
        return clinician_assigned(db, user.id, patient.id)
    return False


def can_view_clinical_detail(db: DbSession, user: User, patient: PatientProfile) -> bool:
    """Clinician-only sections: notes, raw signal diagnostics, device internals."""
    return is_admin(user) or (
        user.role is Role.PHYSIOTHERAPIST and clinician_assigned(db, user.id, patient.id)
    )


def get_patient_or_403(db: DbSession, user: User, patient_id: int) -> PatientProfile:
    """Fetch a patient the caller is permitted to see.

    A patient the caller may not see is reported as 404, not 403, so the API
    does not confirm the existence of other people's records.
    """
    patient = db.get(PatientProfile, patient_id)
    if patient is None:
        raise PatientNotFound()
    if not can_view_patient(db, user, patient):
        raise PatientNotFound()
    return patient


def require_clinician(user: User) -> None:
    if not is_clinician(user):
        raise Forbidden("This action requires a clinician account.")


def visible_patient_ids(db: DbSession, user: User) -> list[int] | None:
    """Patient ids the caller may see. `None` means unrestricted (admin)."""
    if is_admin(user):
        return None
    if user.role is Role.PATIENT:
        stmt = select(PatientProfile.id).where(PatientProfile.user_id == user.id)
        return [row[0] for row in db.execute(stmt)]
    if user.role is Role.PHYSIOTHERAPIST:
        stmt = select(PatientAssignment.patient_id).where(
            PatientAssignment.clinician_id == user.id,
            PatientAssignment.status == AssignmentStatus.ACTIVE,
        )
        return [row[0] for row in db.execute(stmt)]
    return []


def authorised_session(db: DbSession, user: User, session_id: int):
    """Fetch a session the caller may view, or report it as missing.

    Shared by the REST routes and the live-socket ticket so a socket can never
    be opened on data the same caller could not read over HTTP.
    """
    from app.db.models.session import Session as SessionModel

    session = db.get(SessionModel, session_id)
    if session is None:
        raise SessionNotFound()
    patient = db.get(PatientProfile, session.patient_id)
    if patient is None or not can_view_patient(db, user, patient):
        raise SessionNotFound()
    return session
