"""The authentication flow a browser actually performs.

These exercise the cookie session end to end: signing up, staying signed in
across requests (the "refresh the browser" case), signing out, and the
guarantees that matter -- no token in the response body, no credential
reachable from JavaScript, no session surviving a logout.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import get_settings

PASSWORD = "a-very-long-passphrase"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


def signup(client, email: str | None = None, role: str = "PATIENT", password: str = PASSWORD):
    return client.post("/api/auth/signup", json={
        "email": email or _email(), "password": password, "name": "Test Person", "role": role,
    })


# --- signup --------------------------------------------------------------- #

def test_signup_creates_an_account_and_starts_a_session(client):
    email = _email()
    response = signup(client, email)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == email
    assert body["user"]["role"] == "PATIENT"

    # The session is now established for this client without any further step.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == email


def test_signup_sets_an_httponly_session_cookie(client):
    response = signup(client)
    settings = get_settings()

    cookie_headers = response.headers.get_list("set-cookie")
    session_cookie = [c for c in cookie_headers if c.startswith(settings.cookie_access_name)]
    assert session_cookie, f"no session cookie in {cookie_headers}"

    header = session_cookie[0].lower()
    # HttpOnly is the whole point: a script on the page cannot read this.
    assert "httponly" in header
    assert "samesite=lax" in header


def test_signup_never_returns_a_token_or_a_hash(client):
    """Nothing in the browser response should be a credential."""
    body = signup(client).json()
    serialised = str(body)

    for forbidden in ("access_token", "refresh_token", "password", "password_hash", "token_version"):
        assert forbidden not in serialised, f"{forbidden} leaked into the signup response"


def test_duplicate_email_is_rejected(client):
    email = _email()
    assert signup(client, email).status_code == 201

    duplicate = signup(client, email)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "EMAIL_ALREADY_REGISTERED"


def test_short_password_is_rejected(client):
    response = signup(client, password="short")
    assert response.status_code == 422


def test_malformed_email_is_rejected(client):
    response = client.post("/api/auth/signup", json={
        "email": "not-an-email", "password": PASSWORD, "name": "Test Person",
    })
    assert response.status_code == 422


# --- login ---------------------------------------------------------------- #

def test_login_succeeds_and_persists_across_requests(client):
    email = _email()
    signup(client, email)
    client.post("/api/auth/logout")

    login = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["user"]["email"] == email

    # This is TEST 2 from the brief: a later request is still authenticated,
    # which is what "refresh the browser and stay signed in" comes down to.
    assert client.get("/api/auth/me").status_code == 200


def test_login_with_the_wrong_password_is_refused(client):
    email = _email()
    signup(client, email)
    client.post("/api/auth/logout")

    response = client.post("/api/auth/login", json={"email": email, "password": "wrong-passphrase"})
    assert response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_unknown_and_wrong_password_are_indistinguishable(client):
    """Neither response may reveal whether the account exists."""
    email = _email()
    signup(client, email)
    client.post("/api/auth/logout")

    unknown = client.post("/api/auth/login", json={"email": _email(), "password": PASSWORD})
    wrong = client.post("/api/auth/login", json={"email": email, "password": "wrong-passphrase"})

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["message"] == wrong.json()["message"]


def test_email_is_case_insensitive(client):
    email = _email()
    signup(client, email)
    client.post("/api/auth/logout")

    response = client.post("/api/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert response.status_code == 200


# --- failed-login handling ------------------------------------------------ #

def test_repeated_failures_lock_the_account_then_refuse_the_real_password(client):
    email = _email()
    signup(client, email)
    client.post("/api/auth/logout")
    limit = get_settings().max_failed_logins

    for _ in range(limit):
        client.post("/api/auth/login", json={"email": email, "password": "wrong-passphrase"})

    # The correct password is now refused too: otherwise the lockout would only
    # slow down an attacker who guesses wrong, not one who guesses right.
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 401
    assert "failed sign-in attempts" in response.json()["message"]


def test_a_successful_login_clears_the_failure_count(client, db_session=None):
    email = _email()
    signup(client, email)
    client.post("/api/auth/logout")

    for _ in range(3):
        client.post("/api/auth/login", json={"email": email, "password": "wrong-passphrase"})
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200

    # Three more failures must not now tip an already-counted account over.
    for _ in range(3):
        client.post("/api/auth/login", json={"email": email, "password": "wrong-passphrase"})
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


# --- logout --------------------------------------------------------------- #

def test_logout_ends_the_session(client):
    signup(client)
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_logout_invalidates_tokens_issued_to_other_clients(client):
    """Signing out must not leave a working credential on another device."""
    email = _email()
    signup(client, email)
    pair = client.post("/api/auth/token", json={"email": email, "password": PASSWORD}).json()
    headers = {"Authorization": f"Bearer {pair['access_token']}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_logout_requires_a_session(client):
    assert client.post("/api/auth/logout").status_code == 401


# --- protected routes ----------------------------------------------------- #

@pytest.mark.parametrize("path", [
    "/api/auth/me", "/api/me", "/api/patients", "/api/sessions",
    "/api/reports", "/api/notifications", "/api/devices",
])
def test_protected_endpoints_refuse_anonymous_callers(client, path):
    assert client.get(path).status_code == 401


def test_a_malformed_authorization_header_does_not_fall_back_to_the_cookie(client):
    """An explicit credential that fails must not be papered over by the cookie."""
    signup(client)
    assert client.get("/api/auth/me").status_code == 200

    assert client.get("/api/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


# --- refresh -------------------------------------------------------------- #

def test_refresh_renews_the_session_from_the_cookie(client):
    email = _email()
    signup(client, email)

    response = client.post("/api/auth/refresh")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == email
    assert client.get("/api/auth/me").status_code == 200


def test_refresh_without_a_credential_is_refused(client):
    assert client.post("/api/auth/refresh").status_code == 401


# --- the machine endpoint ------------------------------------------------- #

def test_token_endpoint_returns_a_bearer_pair_for_programs(client):
    email = _email()
    signup(client, email)

    pair = client.post("/api/auth/token", json={"email": email, "password": PASSWORD})
    assert pair.status_code == 200
    body = pair.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert "password" not in str(body)


# --- role self-assignment ------------------------------------------------- #

def test_admin_cannot_be_self_assigned_at_signup(client):
    """An admin can read every patient, so the role must not be self-selectable."""
    response = client.post("/api/auth/signup", json={
        "email": _email(), "password": PASSWORD, "name": "Escalation Attempt", "role": "ADMIN",
    })
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("role", ["PATIENT", "PHYSIOTHERAPIST", "TECHNICIAN"])
def test_ordinary_roles_remain_self_assignable(client, role):
    response = signup(client, role=role)
    assert response.status_code == 201
    assert response.json()["user"]["role"] == role


def test_a_clinician_with_no_assignments_sees_no_patients(client):
    """Self-selecting PHYSIOTHERAPIST grants no access on its own."""
    signup(client, role="PHYSIOTHERAPIST")
    listing = client.get("/api/patients")
    assert listing.status_code == 200
    assert listing.json()["items"] == []
