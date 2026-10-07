"""Continue with Google / Continue with Facebook.

    GET    /auth/providers               sign-in methods this deployment offers
    GET    /auth/{provider}/start        302 to the provider (intent=login|link)
    GET    /auth/{provider}/callback     the provider returns here
    GET    /auth/identities              the signed-in user's sign-in methods
    DELETE /auth/identities/{provider}   disconnect one (never the last)

The browser reaches these through the website's /api/* proxy, so the state
cookie set by /start and the session cookies set by /callback are first-party
to the website -- exactly like email sign-in. A successful callback ends in
the SAME session as /auth/login: the same HttpOnly cookies, issued by the same
`issue_tokens`, read by the same `get_current_user`. There is no separate
"Google session".
"""

from __future__ import annotations

import hmac
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.auth import issue_tokens
from app.api.deps import CurrentUser, DbDep
from app.core.config import get_settings
from app.core.cookies import set_auth_cookies
from app.core.exceptions import AppError, NotFound
from app.core.logging import get_logger, log_event
from app.core.security import decode_token
from app.db.models.audit import AuditAction
from app.db.models.user import Role, User
from app.schemas.user import SELF_ASSIGNABLE_ROLES, IdentityPublic, SignInMethods
from app.services import audit_service, identity_service, oauth
from app.services.oauth import PROVIDERS, OAuthFailure

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger("rehabsense.oauth")

Provider = Literal["google", "facebook"]
Intent = Literal["login", "link"]

# Where each kind of attempt lands when it cannot complete.
_FAILURE_PAGE = {"login": "/login", "link": "/workspace/settings"}


def _safe_next(value: str | None) -> str | None:
    """A same-site page path, or None. Never an absolute or protocol-relative URL."""
    if not value or len(value) > 300:
        return None
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return None
    if any(ord(ch) < 0x20 for ch in value) or value.startswith("/api/"):
        return None
    return value


def _home(role: Role) -> str:
    return "/workspace/patients" if role in (Role.PHYSIOTHERAPIST, Role.ADMIN) else "/workspace"


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    # The callback URL carries a single-use code; keep it out of any Referer.
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _clear_state_cookie(response: RedirectResponse, provider: str) -> None:
    s = get_settings()
    response.delete_cookie(oauth.cookie_name(provider), path=oauth.cookie_path(provider),
                           secure=s.cookie_secure, httponly=True, samesite="lax")


def _failure(provider: str, intent: str, code: str, next_path: str | None = None) -> RedirectResponse:
    params = {"oauth_error": code, "provider": provider}
    if next_path and intent == "login":
        params["next"] = next_path
    response = _redirect(f"{_FAILURE_PAGE[intent]}?{urlencode(params)}")
    _clear_state_cookie(response, provider)
    return response


def _session_user(request: Request, db) -> User | None:
    """The user of the browser session on this request, or None (never raises)."""
    token = request.cookies.get(get_settings().cookie_access_name)
    if not token:
        return None
    try:
        claims = decode_token(token, expected="access")
    except AppError:
        return None
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active or claims.get("ver") != user.token_version:
        return None
    return user


@router.get("/providers")
def providers() -> JSONResponse:
    """Which sign-in methods work on this deployment. Public; no secrets.

    Also used by the sign-in page as its "is the API reachable" probe: it
    needs no database, so it answers fast even while the database wakes.
    """
    s = get_settings()
    body = {"providers": {
        "password": {"enabled": True},
        "google": {"enabled": s.oauth_problem("google") is None},
        "facebook": {"enabled": s.oauth_problem("facebook") is None},
        # No SMS provider is configured; phone sign-in does not exist.
        "phone": {"enabled": False},
    }}
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/{provider}/start")
def start(
    provider: Provider,
    request: Request,
    db: DbDep,
    intent: Intent = "login",
    next_path: str | None = Query(default=None, alias="next"),
    role: str | None = None,
    rerequest: bool = False,
) -> RedirectResponse:
    """Send the browser to the provider's own sign-in page."""
    s = get_settings()
    problem = s.oauth_problem(provider)
    if problem:
        log_event(logger, "oauth_unavailable", provider=provider, reason=problem)
        return _failure(provider, intent, "not_configured")

    user_id = None
    if intent == "link":
        # Connecting a provider needs the account it is being connected to.
        user = _session_user(request, db)
        if user is None:
            return _failure(provider, "login", "link_session_expired", "/workspace/settings")
        user_id = user.id

    requested_role = role if role in {r.value for r in SELF_ASSIGNABLE_ROLES} else None
    pending = oauth.new_pending(provider, intent, user_id, _safe_next(next_path), requested_role,
                                rerequest=rerequest and provider == "facebook")
    response = _redirect(oauth.authorization_url(pending))
    response.set_cookie(
        oauth.cookie_name(provider), oauth.seal(pending),
        max_age=s.oauth_state_minutes * 60, httponly=True, secure=s.cookie_secure,
        # Lax is what lets the cookie ride the provider's top-level GET back
        # to the callback while staying off cross-site subrequests.
        samesite="lax", path=oauth.cookie_path(provider),
    )
    log_event(logger, "oauth_started", provider=provider, intent=intent)
    return response


@router.get("/{provider}/callback")
def callback(
    provider: Provider,
    request: Request,
    db: DbDep,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Verify the provider's answer and finish in the ordinary RehabSense session."""
    s = get_settings()
    pending = oauth.unseal(request.cookies.get(oauth.cookie_name(provider)), provider)
    intent = pending.intent if pending else "login"
    next_path = pending.next_path if pending else None

    def refuse(reason: str, detail: str = "") -> RedirectResponse:
        log_event(logger, "oauth_refused", provider=provider, intent=intent, reason=reason,
                  detail=detail[:200])
        audit_service.record(db, action=AuditAction.OAUTH_LOGIN_REFUSED, entity_type="identity",
                             actor_id=pending.user_id if pending else None, provider=provider,
                             reason=reason)
        db.commit()
        return _failure(provider, intent, reason, next_path)

    if s.oauth_problem(provider):
        return refuse("not_configured")
    # The state must match the one this browser was given at /start ...
    if pending is None:
        return refuse("invalid_state", "state cookie missing, expired or forged")
    if not state or not hmac.compare_digest(state, pending.state):
        return refuse("invalid_state", "state does not match this browser's attempt")
    # ... and must never have been used before, on any instance.
    if not identity_service.consume_state(db, pending):
        return refuse("invalid_state", "state already used")
    if error:
        # access_denied: the person pressed Cancel / Not now on the provider.
        return refuse("cancelled" if error == "access_denied" else "provider_error",
                      f"provider returned error={error[:40]}")
    if not code:
        return refuse("provider_error", "callback without a code")
    if intent == "link":
        current = _session_user(request, db)
        if current is None or current.id != pending.user_id:
            return refuse("link_session_expired", "signed-in account changed during linking")

    try:
        profile = oauth.fetch_profile(provider, code, pending)
        result = identity_service.complete_sign_in(db, profile, pending)
    except OAuthFailure as failure:
        return refuse(failure.code, failure.detail)
    except Exception as exc:  # e.g. a malformed provider response
        # Still a clean refusal in the browser, never a half-made session.
        db.rollback()
        logger.exception("oauth callback failed", extra={"context": {"provider": provider}})
        return refuse("provider_error", f"unexpected {type(exc).__name__}")

    if intent == "link":
        response = _redirect(f"/workspace/settings?{urlencode({'linked': provider})}")
    else:
        response = _redirect(next_path or _home(result.user.role))
        access, refresh = issue_tokens(result.user)
        set_auth_cookies(response, access, refresh)
    _clear_state_cookie(response, provider)
    log_event(logger, "oauth_completed", provider=provider, intent=intent, user_id=result.user.id,
              created=result.created, linked=result.linked)
    return response


@router.get("/identities", response_model=SignInMethods)
def identities(user: CurrentUser, db: DbDep) -> SignInMethods:
    s = get_settings()
    return SignInMethods(
        password=user.password_hash is not None,
        identities=[
            IdentityPublic(provider=i.provider, email=i.provider_email, linked_at=i.created_at,
                           last_used_at=i.last_used_at)
            for i in identity_service.sign_in_methods(db, user)
        ],
        available={p: s.oauth_problem(p) is None for p in PROVIDERS},
    )


@router.delete("/identities/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(provider: Provider, user: CurrentUser, db: DbDep) -> None:
    if not identity_service.unlink(db, user, provider):
        raise NotFound("This sign-in method is not connected to your account.")
