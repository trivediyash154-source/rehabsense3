"""The authenticated user's own profile, and deleting the account."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from app.core.config import get_settings
from app.core.cookies import clear_auth_cookies
from app.core.exceptions import ActiveAssignments, ConfirmationRequired, Forbidden, Unauthorized
from app.core.security import verify_password
from app.db.models.audit import AuditAction
from app.db.models.patient import AssignmentStatus, PatientAssignment
from app.db.models.user import Role
from app.schemas.user import AccountDeletion, UserPublic, UserUpdate
from app.services import audit_service, identity_service

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserPublic)
def me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)


@router.patch("/me", response_model=UserPublic)
def update_me(payload: UserUpdate, user: CurrentUser, db: DbDep) -> UserPublic:
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return UserPublic.model_validate(user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(payload: AccountDeletion, response: Response, user: CurrentUser, db: DbDep) -> None:
    """Permanently delete the signed-in account.

    Removes the user row, every connected sign-in identity (Google, Facebook),
    notifications and the account's own preferences, and ends every session.
    A patient record that a clinician created stays with that clinician's
    records, unlinked from the deleted account. Administrators and clinicians
    with active patient assignments cannot delete themselves here.
    """
    if payload.confirm.strip() != "DELETE":
        raise ConfirmationRequired()
    if user.role is Role.ADMIN:
        raise Forbidden("Administrator accounts are removed by another administrator.")
    active = db.execute(
        select(PatientAssignment.id).where(PatientAssignment.clinician_id == user.id,
                                           PatientAssignment.status == AssignmentStatus.ACTIVE)
    ).first()
    if active is not None:
        raise ActiveAssignments()
    if user.password_hash is not None:
        # Re-authentication, counted against the same lockout as sign-in.
        now = datetime.now(timezone.utc)
        settings = get_settings()
        if user.is_locked(now):
            raise Unauthorized("Too many failed attempts. Please try again in a few minutes.")
        if not payload.password or not verify_password(payload.password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= settings.max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                user.failed_login_count = 0
            db.commit()
            raise Unauthorized("Password is incorrect.")

    user_id, role = user.id, user.role.value
    providers = [i.provider for i in identity_service.sign_in_methods(db, user)]
    db.delete(user)
    # Identifiers only: the deleted person's name and email are not kept.
    audit_service.record(db, action=AuditAction.USER_DELETED, entity_type="user", entity_id=user_id,
                         actor_id=None, role=role, providers=providers)
    db.commit()
    clear_auth_cookies(response)
