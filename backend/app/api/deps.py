"""Request dependencies: DB session, the authenticated caller, CSRF guard."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.core.exceptions import Forbidden, Unauthorized
from app.core.security import decode_token
from app.db.database import get_db
from app.db.models.user import Role, User

DbDep = Annotated[DbSession, Depends(get_db)]

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _resolve_user(db: DbSession, token: str, *, expected: str = "access") -> User:
    payload = decode_token(token, expected=expected)
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise Unauthorized()
    # A token issued before a password change or logout-everywhere is refused.
    if payload.get("ver") != user.token_version:
        raise Unauthorized("Your session is no longer valid. Please sign in again.")
    return user


def get_current_user(
    request: Request,
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Authenticate from a bearer token or the session cookie.

    Bearer wins so that non-browser clients -- the simulator, the firmware and
    the tests -- are unaffected by anything the browser does.
    """
    if authorization is not None:
        # An explicit credential that fails must not be quietly replaced by the
        # ambient cookie: that would make a rejected token look accepted.
        if not authorization.lower().startswith("bearer "):
            raise Unauthorized("Unsupported authorization scheme.")
        return _resolve_user(db, authorization.split(" ", 1)[1])

    settings = get_settings()
    cookie = request.cookies.get(settings.cookie_access_name)
    if not cookie:
        raise Unauthorized()

    # A cookie is attached by the browser automatically, so a cookie-authenticated
    # write needs a second signal that the request came from our own frontend
    # rather than from another site that simply linked to this URL. SameSite=Lax
    # already blocks the cross-site form post; this covers the rest.
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.cors_origins:
            raise Forbidden("Request origin is not allowed.")

    return _resolve_user(db, cookie)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_refresh_token(
    request: Request,
    refresh_cookie: Annotated[str | None, Cookie(alias="rs_refresh")] = None,
) -> str | None:
    """The refresh credential, from its cookie if the caller is a browser."""
    return refresh_cookie or request.cookies.get(get_settings().cookie_refresh_name)


def require_role(*roles: Role):
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles and user.role is not Role.ADMIN:
            raise Forbidden(f"This action requires one of: {', '.join(r.value for r in roles)}.")
        return user

    return dependency
