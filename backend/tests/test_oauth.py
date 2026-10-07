"""Google and Facebook sign-in.

The provider side is stubbed HERE ONLY: an httpx.MockTransport stands in for
Google's token endpoint and Facebook's Graph API, and Google ID tokens are
signed with a throwaway RSA key. Production code has no stub, no test mode and
no way to skip verification; these tests drive the real routes, the real state
handling, the real ID-token verification and the real account-linking policy.
"""

from __future__ import annotations

import logging
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models.identity import UserIdentity
from app.db.models.user import User
from app.services import oauth

GOOGLE_ID = "test-client.apps.googleusercontent.com"
GOOGLE_SECRET = "google-test-secret-DO-NOT-LOG"
FB_ID = "123456789"
FB_SECRET = "facebook-test-secret-DO-NOT-LOG"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Providers:
    """Programmable stand-in for Google and Facebook (tests only)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.google_claims: dict = {}
        self.google_key = KEY
        self.google_status = 200
        self.fb_profile: dict = {}
        self.fb_debug: dict = {}
        self.fb_token = f"EAAG-{uuid.uuid4().hex}"
        self.seen_google_form: dict = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url.split("?")[0])
        if url.startswith(oauth.GOOGLE_TOKEN_URL):
            self.seen_google_form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if self.google_status != 200:
                return httpx.Response(self.google_status, json={"error": "invalid_grant"})
            token = jwt.encode(self.google_claims, self.google_key, algorithm="RS256",
                               headers={"kid": "test"})
            return httpx.Response(200, json={"id_token": token, "access_token": "ya29.test-access",
                                             "token_type": "Bearer", "expires_in": 3599})
        if "/oauth/access_token" in url:
            return httpx.Response(200, json={"access_token": self.fb_token, "token_type": "bearer",
                                             "expires_in": 5183944})
        if "/debug_token" in url:
            return httpx.Response(200, json={"data": self.fb_debug})
        if url.split("?")[0].endswith("/me"):
            return httpx.Response(200, json=self.fb_profile)
        return httpx.Response(404, json={"error": "unexpected"})


@pytest.fixture
def providers(monkeypatch):
    s = get_settings()
    for name, value in {
        "google_client_id": GOOGLE_ID, "google_client_secret": GOOGLE_SECRET,
        "facebook_app_id": FB_ID, "facebook_app_secret": FB_SECRET,
    }.items():
        monkeypatch.setattr(s, name, value)
    stub = Providers()
    monkeypatch.setattr(oauth, "_transport", httpx.MockTransport(stub.handler))
    monkeypatch.setattr(oauth, "_google_signing_key", lambda token: stub.google_key.public_key())
    return stub


def _query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def _start(client, provider="google", **params):
    response = client.get(f"/api/auth/{provider}/start", params=params, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response, _query(response.headers["location"])


def _google_claims(expected_nonce: str, sub: str | None = None, email: str | None = None, **extra) -> dict:
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": GOOGLE_ID, "azp": GOOGLE_ID,
              "sub": sub or f"g-{uuid.uuid4().hex}", "email": email or f"g-{uuid.uuid4().hex[:8]}@example.com",
              "email_verified": True, "name": "Grace Hopper", "iat": now, "exp": now + 3600,
              "nonce": expected_nonce}
    claims.update(extra)
    return claims


def _google_login(client, providers, *, sub=None, email=None, start_params=None, **claim_overrides):
    _, q = _start(client, "google", **(start_params or {}))
    providers.google_claims = _google_claims(q["nonce"], sub=sub, email=email, **claim_overrides)
    return client.get("/api/auth/google/callback", params={"state": q["state"], "code": "4/0-test-code"},
                      follow_redirects=False)


_UNIQUE = object()


def _facebook_login(client, providers, *, fb_id=None, email=_UNIQUE, **start_params):
    if email is _UNIQUE:
        email = f"fb-{uuid.uuid4().hex[:8]}@example.com"
    _, q = _start(client, "facebook", **start_params)
    fb_id = fb_id or str(uuid.uuid4().int)[:16]
    providers.fb_debug = {"app_id": FB_ID, "is_valid": True, "user_id": fb_id}
    providers.fb_profile = {"id": fb_id, "name": "Frances Allen", **({"email": email} if email else {})}
    return client.get("/api/auth/facebook/callback", params={"state": q["state"], "code": "AQB-test-code"},
                      follow_redirects=False)


def _error(response) -> str | None:
    return _query(response.headers["location"]).get("oauth_error")


def _signup(client, email=None, password="a-very-long-passphrase"):
    email = email or f"pw-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": password, "name": "Pat Word"})
    assert r.status_code == 201, r.text
    return email, password


# --- configuration ------------------------------------------------------- #

def test_providers_are_off_until_configured(client):
    body = client.get("/api/auth/providers").json()["providers"]
    assert body["password"]["enabled"] is True
    assert body["google"]["enabled"] is False
    assert body["facebook"]["enabled"] is False
    assert body["phone"]["enabled"] is False


def test_unconfigured_provider_never_redirects_or_signs_in(client):
    response = client.get("/api/auth/google/start", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?")
    assert _error(response) == "not_configured"
    # At most a deletion of a stale state cookie; never a live one.
    for cookie in response.headers.get_list("set-cookie"):
        assert not cookie.startswith("rs_oauth_google=") or "Max-Age=0" in cookie
    assert "rs_session" not in client.cookies


def test_providers_report_enabled_when_configured(client, providers):
    body = client.get("/api/auth/providers").json()["providers"]
    assert body["google"]["enabled"] is True and body["facebook"]["enabled"] is True


@pytest.mark.parametrize("uri,problem", [
    ("https://rehabsense-api.vercel.app/api/auth/google/callback", "website origin"),
    ("http://rehabsense-platform.vercel.app/api/auth/google/callback", "https"),
    ("https://rehabsense-platform.vercel.app/auth/google/callback", "path"),
])
def test_production_rejects_a_redirect_uri_that_would_lose_the_session(monkeypatch, uri, problem):
    from app.core.config import Settings

    s = Settings(environment="production", google_client_id="x", google_client_secret="y",
                 google_redirect_uri=uri, cors_origins=["https://rehabsense-platform.vercel.app"])
    assert problem in (s.oauth_problem("google") or "")


def test_production_accepts_the_website_callback():
    from app.core.config import Settings

    s = Settings(environment="production", google_client_id="x", google_client_secret="y",
                 cors_origins=["https://rehabsense-platform.vercel.app"])
    assert s.oauth_redirect_uri("google") == \
        "https://rehabsense-platform.vercel.app/api/auth/google/callback"
    assert s.oauth_problem("google") is None


# --- start ---------------------------------------------------------------- #

def test_google_start_sends_the_browser_to_google_with_state_nonce_and_pkce(client, providers):
    response, q = _start(client, "google")
    assert response.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["client_id"] == GOOGLE_ID
    assert q["redirect_uri"] == "http://localhost:3000/api/auth/google/callback"
    assert q["response_type"] == "code"
    assert q["scope"] == "openid email profile"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) >= 43
    assert q["prompt"] == "select_account"
    assert len(q["state"]) >= 32 and len(q["nonce"]) >= 32
    assert GOOGLE_SECRET not in response.headers["location"]
    cookie = response.headers["set-cookie"]
    assert "rs_oauth_google=" in cookie and "HttpOnly" in cookie
    assert "Path=/api/auth/google" in cookie and "SameSite=lax" in cookie
    # Nothing has been signed in yet.
    assert "rs_session" not in client.cookies


def test_facebook_start_requests_only_basic_permissions(client, providers):
    response, q = _start(client, "facebook")
    assert response.headers["location"].startswith(
        f"https://www.facebook.com/{get_settings().facebook_graph_version}/dialog/oauth?")
    assert q["client_id"] == FB_ID
    assert q["scope"] == "public_profile,email"
    assert q["redirect_uri"] == "http://localhost:3000/api/auth/facebook/callback"
    assert FB_SECRET not in response.headers["location"]


# --- Google --------------------------------------------------------------- #

def test_google_new_user_lands_in_the_ordinary_session(client, providers, db):
    response = _google_login(client, providers, email="new.google@example.com")
    assert response.status_code == 303
    assert response.headers["location"] == "/workspace"
    session = [c for c in response.headers.get_list("set-cookie") if c.startswith("rs_session=")]
    assert session and "HttpOnly" in session[0] and "SameSite=lax" in session[0]
    # The same /me that email sign-in uses recognises the user.
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "new.google@example.com"
    # The code was exchanged with the secret and the PKCE verifier, server-side.
    assert providers.seen_google_form["client_secret"] == GOOGLE_SECRET
    assert len(providers.seen_google_form["code_verifier"]) >= 43
    user = db.execute(select(User).where(User.email == "new.google@example.com")).scalar_one()
    assert user.password_hash is None
    identity = db.execute(select(UserIdentity).where(UserIdentity.user_id == user.id)).scalar_one()
    assert identity.provider == "google" and identity.provider_email_verified is True


def test_google_returning_user_reaches_the_same_account(client, providers, db):
    sub = f"g-{uuid.uuid4().hex}"
    first = _google_login(client, providers, sub=sub, email="returning@example.com")
    first_id = client.get("/api/auth/me").json()["user"]["id"]
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    second = _google_login(client, providers, sub=sub, email="returning@example.com")
    assert first.status_code == second.status_code == 303
    assert client.get("/api/auth/me").json()["user"]["id"] == first_id
    assert db.execute(select(func.count()).select_from(User)
                      .where(User.email == "returning@example.com")).scalar() == 1
    assert db.execute(select(func.count()).select_from(UserIdentity)
                      .where(UserIdentity.provider_subject == sub)).scalar() == 1


def test_password_sign_in_is_refused_for_an_account_without_a_password(client, providers):
    _google_login(client, providers, email="nopass@example.com")
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"email": "nopass@example.com", "password": "anything-at-all"})
    assert response.status_code == 401
    assert response.json()["message"] == "Email or password is incorrect."


def test_google_cancel_returns_to_login_without_a_session(client, providers):
    _, q = _start(client, "google")
    response = client.get("/api/auth/google/callback", params={"state": q["state"], "error": "access_denied"},
                          follow_redirects=False)
    assert response.headers["location"].startswith("/login?")
    assert _error(response) == "cancelled"
    assert "rs_session" not in client.cookies
    assert oauth.GOOGLE_TOKEN_URL not in providers.calls


@pytest.mark.parametrize("case", ["no_cookie", "wrong_state", "no_state"])
def test_invalid_state_is_refused_before_any_code_exchange(client, providers, case):
    _, q = _start(client, "google")
    params = {"state": q["state"], "code": "4/0-test-code"}
    if case == "no_cookie":
        client.cookies.clear()
    elif case == "wrong_state":
        params["state"] = "x" * 43
    else:
        params.pop("state")
    response = client.get("/api/auth/google/callback", params=params, follow_redirects=False)
    assert _error(response) == "invalid_state"
    assert "rs_session" not in client.cookies
    assert oauth.GOOGLE_TOKEN_URL not in providers.calls


def test_expired_state_is_refused(client, providers, monkeypatch):
    real = time.time
    monkeypatch.setattr(oauth.time, "time", lambda: real() - 3600)  # started an hour ago
    _, q = _start(client, "google")
    monkeypatch.setattr(oauth.time, "time", real)
    response = client.get("/api/auth/google/callback", params={"state": q["state"], "code": "c"},
                          follow_redirects=False)
    assert _error(response) == "invalid_state"
    assert oauth.GOOGLE_TOKEN_URL not in providers.calls


def test_a_replayed_callback_is_refused_even_with_the_cookie(client, providers):
    _, q = _start(client, "google")
    sealed = client.cookies.get("rs_oauth_google")
    providers.google_claims = _google_claims(q["nonce"])
    params = {"state": q["state"], "code": "4/0-test-code"}
    assert client.get("/api/auth/google/callback", params=params, follow_redirects=False) \
        .headers["location"] == "/workspace"
    client.post("/api/auth/logout")
    client.cookies.set("rs_oauth_google", sealed, path="/api/auth/google")
    exchanges = providers.calls.count(oauth.GOOGLE_TOKEN_URL)
    replay = client.get("/api/auth/google/callback", params=params, follow_redirects=False)
    assert _error(replay) == "invalid_state"
    assert providers.calls.count(oauth.GOOGLE_TOKEN_URL) == exchanges
    assert client.get("/api/auth/me").status_code == 401


def test_a_state_from_one_provider_does_not_work_for_another(client, providers):
    _, q = _start(client, "google")
    sealed = client.cookies.get("rs_oauth_google")
    client.cookies.set("rs_oauth_facebook", sealed, path="/api/auth/facebook")
    response = client.get("/api/auth/facebook/callback", params={"state": q["state"], "code": "c"},
                          follow_redirects=False)
    assert _error(response) == "invalid_state"


@pytest.mark.parametrize("tamper", [
    {"aud": "someone-elses-client.apps.googleusercontent.com"},
    {"iss": "https://evil.example.com"},
    {"nonce": "not-the-nonce-we-sent"},
    {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
    {"azp": "someone-elses-client"},
])
def test_google_id_token_must_be_ours(client, providers, tamper):
    response = _google_login(client, providers, **tamper)
    assert _error(response) == "provider_error"
    assert "rs_session" not in client.cookies


def test_google_id_token_signed_by_another_key_is_refused(client, providers, monkeypatch):
    _, q = _start(client, "google")
    providers.google_claims = _google_claims(q["nonce"])
    providers.google_key = OTHER_KEY  # the token is signed with this key...
    # ...while verification uses Google's published key.
    monkeypatch.setattr(oauth, "_google_signing_key", lambda token: KEY.public_key())
    response = client.get("/api/auth/google/callback", params={"state": q["state"], "code": "c"},
                          follow_redirects=False)
    assert _error(response) == "provider_error"
    assert "rs_session" not in client.cookies


def test_failed_code_exchange_is_a_clean_error(client, providers):
    providers.google_status = 400
    response = _google_login(client, providers)
    assert _error(response) == "provider_error"
    assert "rs_session" not in client.cookies


def test_unverified_google_email_does_not_create_an_account(client, providers, db):
    response = _google_login(client, providers, email="unverified@example.com", email_verified=False)
    assert _error(response) == "email_unverified"
    assert db.execute(select(User).where(User.email == "unverified@example.com")).scalar_one_or_none() is None


# --- account linking ------------------------------------------------------ #

def test_same_email_password_account_is_never_merged_automatically(client, providers, db):
    email, password = _signup(client)
    client.post("/api/auth/logout")
    response = _google_login(client, providers, email=email)
    assert _error(response) == "account_exists"
    assert "rs_session" not in client.cookies
    assert db.execute(select(func.count()).select_from(User).where(User.email == email)).scalar() == 1
    user = db.execute(select(User).where(User.email == email)).scalar_one()
    assert db.execute(select(UserIdentity).where(UserIdentity.user_id == user.id)).first() is None


def test_linking_requires_signing_in_to_the_existing_account_first(client, providers, db):
    email, password = _signup(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    sub = f"g-{uuid.uuid4().hex}"
    response = _google_login(client, providers, sub=sub, email=email,
                             start_params={"intent": "link"})
    assert response.headers["location"] == "/workspace/settings?linked=google"
    client.post("/api/auth/logout")
    # From now on Google signs in to that same account.
    _google_login(client, providers, sub=sub, email=email)
    assert client.get("/api/auth/me").json()["user"]["id"] == user_id
    methods = client.get("/api/auth/identities").json()
    assert methods["password"] is True
    assert [i["provider"] for i in methods["identities"]] == ["google"]


def test_link_without_a_session_is_refused(client, providers):
    response = client.get("/api/auth/google/start", params={"intent": "link"}, follow_redirects=False)
    assert _error(response) == "link_session_expired"
    assert "accounts.google.com" not in response.headers["location"]


def test_an_identity_already_on_another_account_is_never_moved(client, providers):
    sub = f"g-{uuid.uuid4().hex}"
    _google_login(client, providers, sub=sub)  # creates account A with this Google identity
    owner = client.get("/api/auth/me").json()["user"]["id"]
    client.post("/api/auth/logout")
    _signup(client)  # account B
    response = _google_login(client, providers, sub=sub, start_params={"intent": "link"})
    assert _error(response) == "identity_in_use"
    client.post("/api/auth/logout")
    _google_login(client, providers, sub=sub)
    assert client.get("/api/auth/me").json()["user"]["id"] == owner


def test_disconnect_keeps_at_least_one_way_in(client, providers):
    _google_login(client, providers)
    refused = client.delete("/api/auth/identities/google")
    assert refused.status_code == 409 and refused.json()["code"] == "LAST_SIGN_IN_METHOD"
    _facebook_login(client, providers, email=None, intent="link")
    assert client.delete("/api/auth/identities/google").status_code == 204
    assert [i["provider"] for i in client.get("/api/auth/identities").json()["identities"]] == ["facebook"]


# --- Facebook ------------------------------------------------------------- #

def test_facebook_new_user_lands_in_the_ordinary_session(client, providers, db):
    response = _facebook_login(client, providers, fb_id="10220001", email="fb.new@example.com")
    assert response.headers["location"] == "/workspace"
    assert client.get("/api/auth/me").json()["user"]["email"] == "fb.new@example.com"
    identity = db.execute(select(UserIdentity).where(UserIdentity.provider_subject == "10220001")).scalar_one()
    assert identity.provider == "facebook"
    # Facebook does not vouch for the address.
    assert identity.provider_email_verified is False


def test_facebook_returning_user_and_logout(client, providers, db):
    _facebook_login(client, providers, fb_id="10220002", email="fb.back@example.com")
    first = client.get("/api/auth/me").json()["user"]["id"]
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    _facebook_login(client, providers, fb_id="10220002", email="fb.back@example.com")
    assert client.get("/api/auth/me").json()["user"]["id"] == first
    assert db.execute(select(func.count()).select_from(User).where(User.email == "fb.back@example.com")).scalar() == 1


def test_facebook_token_for_another_app_is_refused(client, providers):
    _, q = _start(client, "facebook")
    providers.fb_debug = {"app_id": "999999", "is_valid": True, "user_id": "1"}
    providers.fb_profile = {"id": "1", "email": "x@example.com"}
    response = client.get("/api/auth/facebook/callback", params={"state": q["state"], "code": "c"},
                          follow_redirects=False)
    assert _error(response) == "provider_error"
    assert "rs_session" not in client.cookies


def test_facebook_profile_must_match_the_inspected_token(client, providers):
    _, q = _start(client, "facebook")
    providers.fb_debug = {"app_id": FB_ID, "is_valid": True, "user_id": "111"}
    providers.fb_profile = {"id": "222", "email": "x@example.com"}
    response = client.get("/api/auth/facebook/callback", params={"state": q["state"], "code": "c"},
                          follow_redirects=False)
    assert _error(response) == "provider_error"


def test_facebook_cancel_returns_to_login(client, providers):
    _, q = _start(client, "facebook")
    response = client.get("/api/auth/facebook/callback", params={
        "state": q["state"], "error": "access_denied", "error_reason": "user_denied",
        "error_description": "Permissions error"}, follow_redirects=False)
    assert _error(response) == "cancelled"
    assert "rs_session" not in client.cookies


def test_facebook_without_an_email_cannot_create_an_account(client, providers):
    response = _facebook_login(client, providers, email=None)
    assert _error(response) == "email_required"
    assert "rs_session" not in client.cookies


def test_facebook_email_matching_an_account_is_refused_not_merged(client, providers):
    email, _ = _signup(client)
    client.post("/api/auth/logout")
    response = _facebook_login(client, providers, email=email)
    assert _error(response) == "account_exists"
    assert "rs_session" not in client.cookies


# --- redirects, roles, secrets ------------------------------------------- #

@pytest.mark.parametrize("next_path,landing", [
    ("/workspace/hardware", "/workspace/hardware"),
    ("https://evil.example.com/", "/workspace"),
    ("//evil.example.com/", "/workspace"),
    ("/\\evil.example.com", "/workspace"),
    ("/api/auth/logout", "/workspace"),
])
def test_only_same_site_pages_are_accepted_as_the_landing_page(client, providers, next_path, landing):
    response = _google_login(client, providers, start_params={"next": next_path})
    assert response.headers["location"] == landing


@pytest.mark.parametrize("asked,granted", [
    ("PHYSIOTHERAPIST", "PHYSIOTHERAPIST"), ("TECHNICIAN", "TECHNICIAN"), ("ADMIN", "PATIENT"),
    (None, "PATIENT"),
])
def test_new_social_accounts_get_only_a_self_assignable_role(client, providers, asked, granted):
    _google_login(client, providers, start_params={"role": asked} if asked else {})
    assert client.get("/api/auth/me").json()["user"]["role"] == granted


def test_no_secret_code_or_token_reaches_the_logs(client, providers, caplog):
    caplog.set_level(logging.DEBUG)
    _google_login(client, providers)
    client.post("/api/auth/logout")
    _facebook_login(client, providers)
    text = "\n".join(f"{r.getMessage()} {getattr(r, 'context', '')}" for r in caplog.records)
    for secret in (GOOGLE_SECRET, FB_SECRET, "4/0-test-code", "AQB-test-code", providers.fb_token,
                   "ya29.test-access"):
        assert secret not in text


def test_session_cookie_from_social_login_is_the_standard_one(client, providers):
    response = _google_login(client, providers)
    names = sorted(c.split("=", 1)[0] for c in response.headers.get_list("set-cookie"))
    # rs_session + rs_refresh (the email-login pair) and the cleared state cookie.
    assert names == ["rs_oauth_google", "rs_refresh", "rs_session"]


# --- account deletion ----------------------------------------------------- #

def test_deleting_a_password_account_needs_the_password(client):
    email, password = _signup(client)
    assert client.request("DELETE", "/api/me", json={"confirm": "DELETE", "password": "wrong-password-x"}).status_code == 401
    assert client.request("DELETE", "/api/me", json={"confirm": "nope", "password": password}).status_code == 400
    assert client.request("DELETE", "/api/me", json={"confirm": "DELETE", "password": password}).status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 401


def test_deleting_a_social_account_removes_its_identities(client, providers, db):
    sub = f"g-{uuid.uuid4().hex}"
    _google_login(client, providers, sub=sub)
    assert client.request("DELETE", "/api/me", json={"confirm": "DELETE"}).status_code == 204
    assert db.execute(select(UserIdentity).where(UserIdentity.provider_subject == sub)).first() is None
    # Signing in with the same Google account again starts a fresh account.
    _google_login(client, providers, sub=sub)
    assert client.get("/api/auth/me").status_code == 200


def test_a_malformed_provider_response_is_a_clean_refusal(client, providers, monkeypatch):
    _, q = _start(client, "google")

    def broken(request):
        return httpx.Response(200, content=b"<html>not json</html>")

    monkeypatch.setattr(oauth, "_transport", httpx.MockTransport(broken))
    response = client.get("/api/auth/google/callback", params={"state": q["state"], "code": "c"},
                          follow_redirects=False)
    assert response.status_code == 303
    assert _error(response) == "provider_error"
    assert "rs_session" not in client.cookies
