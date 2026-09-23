"""Session cookies for browser clients.

The browser never handles a raw token. It reaches this API through the
frontend's `/api/*` proxy, which makes these cookies first-party, so:

* `HttpOnly` puts the session out of reach of every script on the page. A
  token in `localStorage` is readable by any injected script; this is not.
* `SameSite=Lax` stops another site from making a state-changing request that
  silently carries the user's session.
* `Secure` (required outside development) keeps it off plaintext HTTP.

Non-browser callers -- the simulator, the firmware, CI -- keep using
`Authorization: Bearer`, so the hardware contract is untouched.
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import get_settings


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_access_name,
        access_token,
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=settings.cookie_path,
        domain=settings.cookie_domain,
    )
    response.set_cookie(
        settings.cookie_refresh_name,
        refresh_token,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        # Scoped to the refresh endpoint, so the long-lived credential is not
        # attached to every ordinary API call.
        path=f"{settings.api_prefix}/auth/refresh",
        domain=settings.cookie_domain,
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.cookie_access_name,
        path=settings.cookie_path,
        domain=settings.cookie_domain,
    )
    response.delete_cookie(
        settings.cookie_refresh_name,
        path=f"{settings.api_prefix}/auth/refresh",
        domain=settings.cookie_domain,
    )
