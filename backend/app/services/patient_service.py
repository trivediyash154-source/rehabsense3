"""Patient records and clinician assignment."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db.models.audit import AuditAction
from app.db.models.patient import AssignmentStatus, PatientAssignment, PatientProfile
from app.db.models.user import Role, User
from app.schemas.patient import PatientCreate, PatientUpdate
from app.services import audit_service


def create_patient(db: DbSession, payload: PatientCreate, actor: User) -> PatientProfile:
    patient = PatientProfile(
        name=payload.name,
        age=payload.age,
        sex=payload.sex,
        operated_leg=payload.operated_leg,
        surgery_date=payload.surgery_date,
        notes=payload.notes,
        user_id=payload.user_id,
    )
    db.add(patient)
    db.flush()

    # The creating clinician is assigned automatically, otherwise nobody
    # (including the creator) would be authorised to read the record back.
    if actor.role in (Role.PHYSIOTHERAPIST, Role.ADMIN):
        assign_clinician(db, patient_id=patient.id, clinician_id=actor.id)

    audit_service.record(
        db, action=AuditAction.PATIENT_CREATED, entity_type="patient",
        entity_id=patient.id, actor_id=actor.id, operated_leg=payload.operated_leg.value,
    )
    return patient


def update_patient(db: DbSession, patient: PatientProfile, payload: PatientUpdate, actor: User) -> PatientProfile:
    changed: list[str] = []
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(patient, field, value)
            changed.append(field)
    db.flush()
    audit_service.record(
        db,
        action=AuditAction.NOTE_UPDATED if "notes" in changed else AuditAction.PATIENT_UPDATED,
        entity_type="patient", entity_id=patient.id, actor_id=actor.id,
        # Field names only — never the note contents.
        fields=changed,
    )
    return patient


def assign_clinician(db: DbSession, *, patient_id: int, clinician_id: int) -> PatientAssignment:
    existing = db.execute(
        select(PatientAssignment).where(
            PatientAssignment.patient_id == patient_id,
            PatientAssignment.clinician_id == clinician_id,
        )
    ).scalar_one_or_none()
    if existing:
        existing.status = AssignmentStatus.ACTIVE
        existing.ended_at = None
        return existing
    assignment = PatientAssignment(
        patient_id=patient_id,
        clinician_id=clinician_id,
        status=AssignmentStatus.ACTIVE,
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(assignment)
    db.flush()
    return assignment


def list_patients(
    db: DbSession,
    *,
    allowed_ids: list[int] | None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PatientProfile], int]:
    stmt = select(PatientProfile)
    count_stmt = select(func.count(PatientProfile.id))

    if allowed_ids is not None:
        if not allowed_ids:
            return [], 0
        stmt = stmt.where(PatientProfile.id.in_(allowed_ids))
        count_stmt = count_stmt.where(PatientProfile.id.in_(allowed_ids))

    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(PatientProfile.name.ilike(pattern))
        count_stmt = count_stmt.where(PatientProfile.name.ilike(pattern))

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(PatientProfile.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return list(rows), total


def list_for_ids(db: DbSession, allowed: list[int] | None) -> list[PatientProfile]:
    """Patients the caller may see. `None` means unrestricted (admin)."""
    stmt = select(PatientProfile).order_by(PatientProfile.name)
    if allowed is not None:
        if not allowed:
            return []
        stmt = stmt.where(PatientProfile.id.in_(allowed))
    return list(db.execute(stmt).scalars())
