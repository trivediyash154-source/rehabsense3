"""Turning a provider-verified identity into a RehabSense account.

Account-linking policy (AUTHENTICATION_ARCHITECTURE.md describes it in full):

1. An identity is matched ONLY by (provider, provider_subject). An email
   address is never treated as proof of anything.
2. Known identity -> sign in to the account it belongs to.
3. Unknown identity, and no account uses its email -> create a new account
   (Google requires `email_verified`; Facebook must share an email at all).
4. Unknown identity, but an account already uses that email -> refuse with
   ACCOUNT_EXISTS. Nothing is merged and no second account is created. The
   person signs in to that account the way they did before, then connects the
   provider from Settings (intent="link"), proving ownership of both sides.
   Auto-merging by email would hand the account to whoever registered the
   address first: RehabSense does not verify the email of password accounts.
5. Linking attaches an identity to the account that is signed in *right now*
   and never moves an identity that already belongs to someone else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.core.exceptions import LastSignInMethod
from app.db.models.audit import AuditAction
from app.db.models.identity import OAuthStateUse, UserIdentity
from app.db.models.user import Role, User
from app.schemas.user import SELF_ASSIGNABLE_ROLES
from app.services import audit_service
from app.services.oauth import OAuthFailure, PendingSignIn, ProviderProfile, state_hash

_EMAIL = TypeAdapter(EmailStr)


@dataclass(frozen=True)
class SignInResult:
    user: User
    created: bool = False
    linked: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def consume_state(db: DbSession, pending: PendingSignIn) -> bool:
    """Mark this attempt's state used. False if it was used before (a replay)."""
    now = _now()
    # Housekeeping: states older than a day can never verify again anyway.
    db.execute(delete(OAuthStateUse).where(OAuthStateUse.used_at < now - timedelta(days=1)))
    db.add(OAuthStateUse(state_hash=state_hash(pending.state), provider=pending.provider, used_at=now))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _clean_email(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return str(_EMAIL.validate_python(raw.strip())).lower()
    except ValidationError:
        return None


def _display_name(profile: ProviderProfile, email: str) -> str:
    name = " ".join((profile.name or "").split())[:120]
    if len(name) >= 2:
        return name
    local = email.split("@", 1)[0][:120]
    return local if len(local) >= 2 else "RehabSense user"


def _role(value: str | None) -> Role:
    try:
        role = Role(value) if value else Role.PATIENT
    except ValueError:
        return Role.PATIENT
    # Least privilege: only what a person may pick for themselves at signup.
    return role if role in SELF_ASSIGNABLE_ROLES else Role.PATIENT


def _find(db: DbSession, provider: str, subject: str) -> UserIdentity | None:
    return db.execute(
        select(UserIdentity).where(UserIdentity.provider == provider,
                                   UserIdentity.provider_subject == subject)
    ).scalar_one_or_none()


def _touch(identity: UserIdentity, profile: ProviderProfile, now: datetime) -> None:
    identity.last_used_at = now
    email = _clean_email(profile.email)
    if email:
        identity.provider_email = email
        identity.provider_email_verified = profile.email_verified


def _sign_in_existing(db: DbSession, identity: UserIdentity, profile: ProviderProfile) -> SignInResult:
    user = identity.user
    if not user.is_active:
        raise OAuthFailure("account_disabled", f"user {user.id} is disabled")
    now = _now()
    _touch(identity, profile, now)
    user.last_login_at = now
    audit_service.record(db, action=AuditAction.OAUTH_LOGIN, entity_type="user", entity_id=user.id,
                         actor_id=user.id, provider=profile.provider)
    db.commit()
    db.refresh(user)
    return SignInResult(user)


def _link(db: DbSession, profile: ProviderProfile, user_id: int | None) -> SignInResult:
    user = db.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise OAuthFailure("link_session_expired", "linking user missing or inactive")
    identity = _find(db, profile.provider, profile.subject)
    if identity is not None:
        if identity.user_id != user.id:
            raise OAuthFailure("identity_in_use",
                               f"{profile.provider} identity belongs to another account")
        _touch(identity, profile, _now())
        db.commit()
        return SignInResult(user)
    already = db.execute(
        select(UserIdentity).where(UserIdentity.user_id == user.id,
                                   UserIdentity.provider == profile.provider)
    ).scalar_one_or_none()
    if already is not None:
        raise OAuthFailure("provider_already_linked",
                           f"user {user.id} already has a different {profile.provider} account")
    now = _now()
    db.add(UserIdentity(user_id=user.id, provider=profile.provider, provider_subject=profile.subject,
                        provider_email=_clean_email(profile.email),
                        provider_email_verified=profile.email_verified, last_used_at=now))
    audit_service.record(db, action=AuditAction.IDENTITY_LINKED, entity_type="user", entity_id=user.id,
                         actor_id=user.id, provider=profile.provider)
    try:
        db.commit()
    except IntegrityError:
        # The same provider account was linked elsewhere a moment ago.
        db.rollback()
        raise OAuthFailure("identity_in_use", "concurrent link of the same identity")
    db.refresh(user)
    return SignInResult(user, linked=True)


def complete_sign_in(db: DbSession, profile: ProviderProfile, pending: PendingSignIn) -> SignInResult:
    """Apply the linking policy to a provider-verified identity."""
    if pending.intent == "link":
        return _link(db, profile, pending.user_id)

    identity = _find(db, profile.provider, profile.subject)
    if identity is not None:
        return _sign_in_existing(db, identity, profile)

    if profile.provider == "google" and not profile.email_verified:
        raise OAuthFailure("email_unverified", "google email not verified")
    email = _clean_email(profile.email)
    if email is None:
        raise OAuthFailure("email_required", f"{profile.provider} shared no usable email")
    if db.execute(select(User.id).where(User.email == email)).first() is not None:
        raise OAuthFailure("account_exists", f"email already belongs to an account ({profile.provider})")

    now = _now()
    user = User(email=email, password_hash=None, name=_display_name(profile, email),
                role=_role(pending.role), last_login_at=now)
    db.add(user)
    db.flush()
    db.add(UserIdentity(user_id=user.id, provider=profile.provider, provider_subject=profile.subject,
                        provider_email=email, provider_email_verified=profile.email_verified,
                        last_used_at=now))
    audit_service.record(db, action=AuditAction.USER_REGISTERED, entity_type="user", entity_id=user.id,
                         actor_id=user.id, role=user.role.value, method=profile.provider)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Either a parallel callback for the same person created the account
        # first (sign in to it), or the email was registered in between.
        identity = _find(db, profile.provider, profile.subject)
        if identity is not None:
            return _sign_in_existing(db, identity, profile)
        raise OAuthFailure("account_exists", "email registered concurrently")
    db.refresh(user)
    return SignInResult(user, created=True)


def sign_in_methods(db: DbSession, user: User) -> list[UserIdentity]:
    return list(db.execute(
        select(UserIdentity).where(UserIdentity.user_id == user.id).order_by(UserIdentity.provider)
    ).scalars())


def unlink(db: DbSession, user: User, provider: str) -> bool:
    """Remove one provider from the account, never its last way in."""
    methods = sign_in_methods(db, user)
    target = next((m for m in methods if m.provider == provider), None)
    if target is None:
        return False
    remaining = len(methods) - 1 + (1 if user.password_hash else 0)
    if remaining < 1:
        raise LastSignInMethod()
    db.delete(target)
    audit_service.record(db, action=AuditAction.IDENTITY_UNLINKED, entity_type="user",
                         entity_id=user.id, actor_id=user.id, provider=provider)
    db.commit()
    return True
