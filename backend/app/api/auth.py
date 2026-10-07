"""Signup, login, refresh, logout and the live-socket ticket.

Two client shapes are supported deliberately:

* **Browsers** use `/signup`, `/login`, `/logout` and `/me`. These set and
  clear HttpOnly cookies and return only the user object -- no token ever
  reaches JavaScript, so an injected script has nothing to steal.
* **Programs** (the simulator, the seed script, CI, future firmware tooling)
  use `/token`, which returns a bearer pair. This keeps the hardware and
  tooling contract independent of anything the browser does.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep, get_refresh_token
from app.core.config import get_settings
from app.core.cookies import clear_auth_cookies, set_auth_cookies
from app.core.exceptions import EmailAlreadyRegistered, Unauthorized
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_ws_ticket,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.db.models.audit import AuditAction
from app.db.models.user import User
from app.schemas.user import (
    AuthResponse,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserLogin,
    UserPublic,
    WsTicketRequest,
    WsTicketResponse,
)
from app.services import audit_service, authz

router = APIRouter(prefix="/auth", tags=["auth"])


def issue_tokens(user: User) -> tuple[str, str]:
    """The (access, refresh) pair for a session -- the same for every sign-in method."""
    return (
        create_access_token(user.id, user.role.value, user.token_version),
        create_refresh_token(user.id, user.token_version),
    )


def _establish(response: Response, user: User) -> AuthResponse:
    """Start a browser session: cookies out, user object back, no token."""
    access, refresh = issue_tokens(user)
    set_auth_cookies(response, access, refresh)
    return AuthResponse(
        user=UserPublic.model_validate(user),
        expires_in=get_settings().access_token_minutes * 60,
    )


def _create_user(payload: UserCreate, db: DbDep) -> User:
    existing = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()
    if existing:
        raise EmailAlreadyRegistered()

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        name=payload.name,
        phone=payload.phone,
        role=payload.role,
    )
    db.add(user)
    db.flush()
    audit_service.record(
        db, action=AuditAction.USER_REGISTERED, entity_type="user",
        entity_id=user.id, actor_id=user.id, role=user.role.value,
    )
    db.commit()
    db.refresh(user)
    return user


def _authenticate(payload: UserLogin, db: DbDep) -> User:
    """Verify credentials, applying and maintaining the lockout window."""
    now = datetime.now(timezone.utc)
    settings = get_settings()
    user = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()

    # Identical response whether the email is unknown or the password is wrong,
    # so the endpoint cannot be used to enumerate accounts.
    if user is None:
        raise Unauthorized("Email or password is incorrect.")

    if user.is_locked(now):
        audit_service.record(
            db, action=AuditAction.USER_LOGIN_BLOCKED, entity_type="user",
            entity_id=user.id, actor_id=user.id,
        )
        db.commit()
        raise Unauthorized(
            "Too many failed sign-in attempts. Please try again in a few minutes."
        )

    # An account created through Google or Facebook has no password: refused
    # exactly like a wrong one, so this endpoint reveals nothing about it.
    if user.password_hash is None or not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
        audit_service.record(
            db, action=AuditAction.USER_LOGIN_FAILED, entity_type="user",
            entity_id=user.id, actor_id=user.id,
        )
        db.commit()
        raise Unauthorized("Email or password is incorrect.")

    if not user.is_active:
        raise Unauthorized("This account is disabled.")

    # Argon2 parameters can be raised over time; upgrade transparently on a
    # successful sign-in, while the plaintext is legitimately in hand.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    audit_service.record(
        db, action=AuditAction.USER_LOGIN, entity_type="user",
        entity_id=user.id, actor_id=user.id,
    )
    db.commit()
    db.refresh(user)
    return user


# --- browser session ------------------------------------------------------ #

@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, response: Response, db: DbDep) -> AuthResponse:
    return _establish(response, _create_user(payload, db))


# The original name, kept so existing tooling and scripts keep working.
@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED,
             include_in_schema=False)
def register(payload: UserCreate, response: Response, db: DbDep) -> AuthResponse:
    return _establish(response, _create_user(payload, db))


@router.post("/login", response_model=AuthResponse)
def login(payload: UserLogin, response: Response, db: DbDep) -> AuthResponse:
    return _establish(response, _authenticate(payload, db))


@router.get("/me", response_model=AuthResponse)
def me(user: CurrentUser) -> AuthResponse:
    """Who the session belongs to. The frontend calls this on every load."""
    return AuthResponse(
        user=UserPublic.model_validate(user),
        expires_in=get_settings().access_token_minutes * 60,
    )


@router.post("/refresh", response_model=AuthResponse)
def refresh(
    response: Response,
    db: DbDep,
    payload: RefreshRequest | None = None,
    cookie_token: str | None = Depends(get_refresh_token),
) -> AuthResponse:
    token = (payload.refresh_token if payload else None) or cookie_token
    if not token:
        raise Unauthorized("No refresh credential was supplied.")
    claims = decode_token(token, expected="refresh")
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active or claims.get("ver") != user.token_version:
        raise Unauthorized("This session is no longer valid.")
    return _establish(response, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: CurrentUser, response: Response, db: DbDep) -> None:
    """End the session everywhere and clear the browser's cookies.

    Bumping `token_version` invalidates every token already issued, so a copy
    taken from another device stops working too.
    """
    user.token_version += 1
    audit_service.record(
        db, action=AuditAction.USER_LOGOUT, entity_type="user",
        entity_id=user.id, actor_id=user.id,
    )
    db.commit()
    clear_auth_cookies(response)


# --- programmatic clients ------------------------------------------------- #

@router.post("/token", response_model=TokenPair)
def token(payload: UserLogin, db: DbDep) -> TokenPair:
    """Bearer tokens for non-browser clients.

    Separate from `/login` so that browser sessions never carry a token
    through JavaScript, while the simulator and firmware tooling keep a
    stable, header-based contract.
    """
    user = _authenticate(payload, db)
    access, refresh_token = issue_tokens(user)
    return TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_minutes * 60,
        user=UserPublic.model_validate(user),
    )


@router.post("/ws-ticket", response_model=WsTicketResponse)
def ws_ticket(payload: WsTicketRequest, request: Request, user: CurrentUser, db: DbDep) -> WsTicketResponse:
    """Authorise one live-session socket for the caller.

    A browser cannot send an Authorization header when opening a WebSocket, so
    the socket is authorised here instead -- against the same patient rules the
    REST API applies -- and handed a ticket that is valid for one session id
    and about a minute.
    """
    session = authz.authorised_session(db, user, payload.session_id)
    return WsTicketResponse(
        ticket=create_ws_ticket(user.id, session.id),
        session_id=session.id,
        expires_in=60,
    )
