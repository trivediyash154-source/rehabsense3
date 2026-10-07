"""Google and Facebook sign-in: the provider side of the authorization-code flow.

The browser is only ever sent to the provider's own sign-in page and back.
Everything that proves who the person is happens here, server to server:

* **Google** (OpenID Connect): the code is exchanged with the client secret and
  a PKCE verifier; the returned ID token's RS256 signature is checked against
  Google's published keys, along with its issuer, audience, expiry and the
  nonce this server generated for the attempt.
* **Facebook**: the code is exchanged with the app secret; the access token is
  then inspected with `debug_token` (it must be valid and issued to *this*
  app), and the profile is read with an `appsecret_proof`.

Provider tokens are used once to read the identity and then discarded; none
is stored, logged or returned to the browser. `state` binds the callback to
the browser that started the attempt (a signed, short-lived HttpOnly cookie)
and is single-use across instances (see `OAuthStateUse`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import get_settings

PROVIDERS = ("google", "facebook")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

FACEBOOK_DIALOG_URL = "https://www.facebook.com/{version}/dialog/oauth"
FACEBOOK_TOKEN_URL = "https://graph.facebook.com/{version}/oauth/access_token"
FACEBOOK_DEBUG_URL = "https://graph.facebook.com/{version}/debug_token"
FACEBOOK_ME_URL = "https://graph.facebook.com/{version}/me"

HTTP_TIMEOUT_S = 10.0
_STATE_TYPE = "oauth_state"

# Tests swap in an httpx.MockTransport. Production always uses the network.
_transport: httpx.BaseTransport | None = None
_google_jwks: jwt.PyJWKClient | None = None


class OAuthFailure(Exception):
    """A sign-in that must not complete.

    `code` is a stable value the website turns into a message; `detail` is for
    the server log only and never contains a code, token or secret.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    subject: str
    email: str | None
    email_verified: bool
    name: str | None


@dataclass(frozen=True)
class PendingSignIn:
    """One started sign-in, carried in the signed state cookie."""

    provider: str
    state: str
    nonce: str
    verifier: str
    intent: str  # "login" | "link"
    user_id: int | None  # the signed-in user, for intent="link"
    next_path: str | None
    role: str | None  # role for a brand-new account (self-assignable only)
    rerequest: bool = False


def cookie_name(provider: str) -> str:
    return f"rs_oauth_{provider}"


def cookie_path(provider: str) -> str:
    return f"{get_settings().api_prefix}/auth/{provider}"


def new_pending(provider: str, intent: str, user_id: int | None, next_path: str | None,
                role: str | None, rerequest: bool = False) -> PendingSignIn:
    return PendingSignIn(
        provider=provider,
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        # RFC 7636: 43-128 characters from the unreserved set.
        verifier=secrets.token_urlsafe(64),
        intent=intent,
        user_id=user_id,
        next_path=next_path,
        role=role,
        rerequest=rerequest,
    )


def seal(pending: PendingSignIn) -> str:
    """Sign the pending attempt for its cookie. HS256 with the API secret."""
    s = get_settings()
    now = int(time.time())
    claims = {
        "typ": _STATE_TYPE, "p": pending.provider, "s": pending.state, "n": pending.nonce,
        "v": pending.verifier, "i": pending.intent, "u": pending.user_id, "nx": pending.next_path,
        "r": pending.role, "rr": pending.rerequest, "iat": now,
        "exp": now + s.oauth_state_minutes * 60,
    }
    return jwt.encode(claims, s.secret_key, algorithm="HS256")


def unseal(token: str | None, provider: str) -> PendingSignIn | None:
    """The pending attempt, or None if absent, forged, expired or for another provider."""
    if not token:
        return None
    try:
        c = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"],
                       options={"require": ["exp", "iat"]})
    except jwt.PyJWTError:
        return None
    if c.get("typ") != _STATE_TYPE or c.get("p") != provider:
        return None
    try:
        return PendingSignIn(
            provider=c["p"], state=str(c["s"]), nonce=str(c["n"]), verifier=str(c["v"]),
            intent=c["i"] if c.get("i") in ("login", "link") else "login",
            user_id=int(c["u"]) if c.get("u") is not None else None,
            next_path=c.get("nx"), role=c.get("r"), rerequest=bool(c.get("rr")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(pending: PendingSignIn) -> str:
    """Where to send the browser: the provider's own sign-in page."""
    s = get_settings()
    redirect_uri = s.oauth_redirect_uri(pending.provider)
    if pending.provider == "google":
        params = {
            "client_id": s.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            # Identity only: no access to anything else in the Google account.
            "scope": "openid email profile",
            "state": pending.state,
            "nonce": pending.nonce,
            "code_challenge": _pkce_challenge(pending.verifier),
            "code_challenge_method": "S256",
            # Always show the account chooser, so a shared computer does not
            # silently sign in as whoever used Google last.
            "prompt": "select_account",
            "access_type": "online",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    if pending.provider == "facebook":
        params = {
            "client_id": s.facebook_app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            # The two permissions Facebook grants without App Review.
            "scope": "public_profile,email",
            "state": pending.state,
        }
        if pending.rerequest:
            params["auth_type"] = "rerequest"  # ask again for a declined email
        version = s.facebook_graph_version
        return f"{FACEBOOK_DIALOG_URL.format(version=version)}?{urlencode(params)}"
    raise OAuthFailure("not_configured", f"unknown provider {pending.provider}")


def _client() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT_S, transport=_transport,
                        headers={"Accept": "application/json"})


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


# --- Google -------------------------------------------------------------- #

def _google_signing_key(id_token: str):
    global _google_jwks
    if _google_jwks is None:
        _google_jwks = jwt.PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True, lifespan=3600,
                                       timeout=HTTP_TIMEOUT_S)
    return _google_jwks.get_signing_key_from_jwt(id_token).key


def _google_profile(code: str, pending: PendingSignIn) -> ProviderProfile:
    s = get_settings()
    with _client() as client:
        response = client.post(GOOGLE_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": s.oauth_redirect_uri("google"),
            "code_verifier": pending.verifier,
        })
    body = _json(response)
    if response.status_code != 200:
        # Google's error code (e.g. invalid_grant for a reused code) is safe to log.
        raise OAuthFailure("provider_error", f"google token exchange {response.status_code} "
                                             f"{body.get('error', '')}".strip())
    id_token = body.get("id_token")
    if not isinstance(id_token, str):
        raise OAuthFailure("provider_error", "google returned no id_token")

    try:
        key = _google_signing_key(id_token)
    except jwt.PyJWKClientConnectionError as exc:
        raise OAuthFailure("provider_unreachable", f"google keys unavailable: {type(exc).__name__}")
    except jwt.PyJWTError as exc:
        raise OAuthFailure("provider_error", f"google id_token key lookup failed: {type(exc).__name__}")
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=s.google_client_id,
            issuer=GOOGLE_ISSUERS,
            leeway=60,
            options={"require": ["iss", "aud", "sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise OAuthFailure("provider_error", f"google id_token rejected: {type(exc).__name__}")
    if not hmac.compare_digest(str(claims.get("nonce", "")), pending.nonce):
        raise OAuthFailure("provider_error", "google id_token nonce mismatch")
    # azp names the client the token was issued to when it differs from aud.
    if claims.get("azp") not in (None, s.google_client_id):
        raise OAuthFailure("provider_error", "google id_token azp mismatch")
    subject = str(claims["sub"])
    if not subject:
        raise OAuthFailure("provider_error", "google id_token without subject")
    verified = claims.get("email_verified") in (True, "true")
    return ProviderProfile("google", subject, claims.get("email"), verified, claims.get("name"))


# --- Facebook ------------------------------------------------------------ #

def _facebook_profile(code: str, pending: PendingSignIn) -> ProviderProfile:
    s = get_settings()
    version = s.facebook_graph_version
    app_id, app_secret = s.facebook_app_id or "", s.facebook_app_secret or ""
    with _client() as client:
        response = client.get(FACEBOOK_TOKEN_URL.format(version=version), params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": s.oauth_redirect_uri("facebook"),
            "code": code,
        })
        body = _json(response)
        token = body.get("access_token")
        if response.status_code != 200 or not isinstance(token, str):
            err = body.get("error") if isinstance(body.get("error"), dict) else {}
            raise OAuthFailure("provider_error", f"facebook token exchange {response.status_code} "
                                                 f"{err.get('type', '')} {err.get('code', '')}".strip())

        # The token must be valid and issued to THIS app, for a known user.
        inspected = client.get(FACEBOOK_DEBUG_URL.format(version=version), params={
            "input_token": token,
            "access_token": f"{app_id}|{app_secret}",
        })
        data = _json(inspected).get("data") or {}
        if inspected.status_code != 200 or data.get("is_valid") is not True \
                or str(data.get("app_id")) != str(app_id) or not data.get("user_id"):
            raise OAuthFailure("provider_error", "facebook token failed debug_token inspection")

        proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        me = client.get(FACEBOOK_ME_URL.format(version=version), params={
            "fields": "id,name,email",
            "access_token": token,
            "appsecret_proof": proof,
        })
    profile = _json(me)
    if me.status_code != 200 or str(profile.get("id")) != str(data.get("user_id")):
        raise OAuthFailure("provider_error", "facebook profile did not match the inspected token")
    # Facebook does not state whether the address is verified: it is treated
    # as unverified and is never used to match an existing account.
    return ProviderProfile("facebook", str(profile["id"]), profile.get("email"), False,
                           profile.get("name"))


def fetch_profile(provider: str, code: str, pending: PendingSignIn) -> ProviderProfile:
    """Exchange the code and return the provider-verified identity."""
    try:
        if provider == "google":
            return _google_profile(code, pending)
        if provider == "facebook":
            return _facebook_profile(code, pending)
    except httpx.HTTPError as exc:
        raise OAuthFailure("provider_unreachable", f"{provider} request failed: {type(exc).__name__}")
    raise OAuthFailure("not_configured", f"unknown provider {provider}")
