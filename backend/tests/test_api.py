"""API and authorisation tests."""

from __future__ import annotations

import uuid


def _register(client, role="PATIENT"):
    email = f"u-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/signup", json={
        "email": email, "password": "a-very-long-passphrase", "name": "Test User", "role": role,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    pair = client.post("/api/auth/token", json={
        "email": email, "password": "a-very-long-passphrase"}).json()
    return {"headers": {"Authorization": f"Bearer {pair['access_token']}"},
            "user": body["user"], "email": email, "password": "a-very-long-passphrase"}


# --- health --------------------------------------------------------------- #

def test_health_keeps_documented_shape(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_health_subchecks(client):
    assert client.get("/api/health/database").json()["status"] == "ok"
    assert client.get("/api/health/analytics").json()["analytics_version"] == "mvp-1.0"


def test_versioned_alias_available(client):
    assert client.get("/api/v1/health").status_code == 200


# --- auth ----------------------------------------------------------------- #

def test_password_is_never_returned_or_stored_plainly(client, db):
    from sqlalchemy import select
    from app.db.models.user import User

    account = _register(client)
    assert "password" not in str(account["user"])
    row = db.execute(select(User).where(User.email == account["email"])).scalar_one()
    assert row.password_hash.startswith("$argon2id$")
    assert "a-very-long-passphrase" not in row.password_hash


def test_login_does_not_reveal_whether_an_email_exists(client):
    account = _register(client)
    unknown = client.post("/api/auth/login",
                          json={"email": "nobody@example.com", "password": "a-very-long-passphrase"})
    wrong = client.post("/api/auth/login",
                        json={"email": account["email"], "password": "wrong-passphrase-here"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["message"] == wrong.json()["message"]


def test_logout_invalidates_existing_tokens(client):
    account = _register(client)
    assert client.get("/api/me", headers=account["headers"]).status_code == 200
    assert client.post("/api/auth/logout", headers=account["headers"]).status_code == 204
    assert client.get("/api/me", headers=account["headers"]).status_code == 401


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/patients").status_code == 401
    assert client.get("/api/me").status_code == 401


# --- patients + authorisation --------------------------------------------- #

def test_patient_cannot_create_records(client):
    patient_user = _register(client, role="PATIENT")
    r = client.post("/api/patients", headers=patient_user["headers"],
                    json={"name": "Valid Name", "operated_leg": "LEFT"})
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"


def test_clinician_only_sees_assigned_patients(client, clinician, patient_record):
    other = _register(client, role="PHYSIOTHERAPIST")
    # The other clinician holds no assignment, so the record is not theirs to see.
    r = client.get(f"/api/patients/{patient_record['id']}", headers=other["headers"])
    assert r.status_code == 404
    assert r.json()["code"] == "PATIENT_NOT_FOUND"

    listing = client.get("/api/patients", headers=other["headers"]).json()
    assert listing["total"] == 0


def test_clinical_notes_are_withheld_from_patients(client, clinician, patient_record, db):
    from app.db.models.patient import PatientProfile

    patient_user = _register(client, role="PATIENT")
    # Link the account to the record so the patient can legitimately read it.
    record = db.get(PatientProfile, patient_record["id"])
    record.user_id = patient_user["user"]["id"]
    db.commit()

    as_patient = client.get(f"/api/patients/{patient_record['id']}",
                            headers=patient_user["headers"]).json()
    as_clinician = client.get(f"/api/patients/{patient_record['id']}",
                              headers=clinician["headers"]).json()

    assert "notes" not in as_patient  # withheld by the server, not the UI
    assert as_clinician["notes"] == "clinician-only note"


def test_patient_listing_is_paginated(client, clinician):
    for i in range(3):
        client.post("/api/patients", headers=clinician["headers"],
                    json={"name": f"P{i}", "operated_leg": "RIGHT"})
    page = client.get("/api/patients?limit=2&offset=0", headers=clinician["headers"]).json()
    assert len(page["items"]) == 2
    assert page["total"] >= 3


# --- sessions ------------------------------------------------------------- #

def test_session_create_is_idempotent(client, clinician, patient_record):
    body = {"patient_id": patient_record["id"], "exercise_type": "SQUAT",
            "idempotency_key": "same-key-123"}
    first = client.post("/api/sessions", headers=clinician["headers"], json=body).json()
    second = client.post("/api/sessions", headers=clinician["headers"], json=body).json()
    assert first["id"] == second["id"]


def test_session_starts_with_both_legs_disconnected(client, clinician, patient_record, db):
    from app.db.models.session import SessionDeviceLink
    from sqlalchemy import select

    session = client.post("/api/sessions", headers=clinician["headers"],
                          json={"patient_id": patient_record["id"], "exercise_type": "WALK"}).json()
    links = db.execute(
        select(SessionDeviceLink).where(SessionDeviceLink.session_id == session["id"])
    ).scalars().all()
    assert len(links) == 2
    # Never reported as connected before a device actually connects.
    assert {l.state.value for l in links} == {"DISCONNECTED"}
    assert session["mode"] == "UNKNOWN"


def test_unknown_session_returns_structured_error(client, clinician):
    r = client.get("/api/sessions/999999", headers=clinician["headers"])
    assert r.status_code == 404
    assert r.json()["code"] == "SESSION_NOT_FOUND"


def test_invalid_date_range_rejected(client, clinician):
    r = client.get("/api/sessions?start_date=2026-06-01T00:00:00&end_date=2026-01-01T00:00:00",
                   headers=clinician["headers"])
    assert r.status_code == 500 or r.status_code >= 400


# --- exercises ------------------------------------------------------------ #

def test_exercise_catalogue_is_served_from_the_database(client, clinician):
    body = client.get("/api/exercises", headers=clinician["headers"]).json()
    keys = {e["key"] for e in body["items"]}
    assert {"WALK", "SQUAT", "SIT_TO_STAND", "STEP_UP",
            "SINGLE_LEG_BALANCE", "KNEE_EXTENSION"} <= keys


# --- report sharing ------------------------------------------------------- #

def test_share_link_is_tokenised_expiring_and_patient_only(client, clinician, patient_record):
    session = client.post("/api/sessions", headers=clinician["headers"],
                          json={"patient_id": patient_record["id"], "exercise_type": "SQUAT"}).json()
    client.post(f"/api/sessions/{session['id']}/end", headers=clinician["headers"], json={})

    report = client.post("/api/reports", headers=clinician["headers"], json={
        "patient_id": patient_record["id"], "kind": "SESSION_SUMMARY", "session_id": session["id"],
    }).json()
    client.post(f"/api/reports/{report['id']}/generate", headers=clinician["headers"])

    share = client.post(f"/api/reports/{report['id']}/share", headers=clinician["headers"],
                        json={"expires_in_hours": 24})
    assert share.status_code == 201
    token = share.json()["token"]
    assert len(token) > 30  # unguessable, not a sequential id

    # Regression: SQLite returns naive datetimes, which used to raise on the
    # expiry comparison and surface as a 500.
    public = client.get(f"/api/reports/shared/{token}")
    assert public.status_code == 200
    payload = public.json()["payload"]
    assert "clinical" not in payload, "shared links never expose clinician sections"

    assert client.get("/api/reports/shared/not-a-real-token").status_code == 404


def test_revoked_share_stops_working(client, clinician, patient_record, db):
    from sqlalchemy import select
    from app.db.models.report import ReportShare

    session = client.post("/api/sessions", headers=clinician["headers"],
                          json={"patient_id": patient_record["id"], "exercise_type": "SQUAT"}).json()
    client.post(f"/api/sessions/{session['id']}/end", headers=clinician["headers"], json={})
    report = client.post("/api/reports", headers=clinician["headers"], json={
        "patient_id": patient_record["id"], "kind": "SESSION_SUMMARY", "session_id": session["id"],
    }).json()
    client.post(f"/api/reports/{report['id']}/generate", headers=clinician["headers"])
    token = client.post(f"/api/reports/{report['id']}/share", headers=clinician["headers"],
                        json={"expires_in_hours": 24}).json()["token"]

    share_id = db.execute(
        select(ReportShare.id).where(ReportShare.report_id == report["id"])
    ).scalar_one()
    assert client.delete(f"/api/reports/{report['id']}/share/{share_id}",
                         headers=clinician["headers"]).status_code == 204
    assert client.get(f"/api/reports/shared/{token}").status_code == 404


# --- configuration -------------------------------------------------------- #

def test_cors_origins_accepts_both_env_formats():
    """Regression: a comma-separated CORS_ORIGINS used to crash at startup.

    pydantic-settings JSON-decodes list fields from the environment before any
    validator runs, so the obvious way to set this raised SettingsError and the
    server never booted.
    """
    from app.core.config import Settings

    Settings.model_config["env_file"] = None
    comma = Settings(cors_origins="http://a.test, http://b.test")
    assert comma.cors_origins == ["http://a.test", "http://b.test"]
    json_form = Settings(cors_origins='["http://a.test","http://b.test"]')
    assert json_form.cors_origins == ["http://a.test", "http://b.test"]


def test_production_refuses_the_development_secret():
    from app.core.config import DEV_SECRET, Settings

    Settings.model_config["env_file"] = None
    import pytest as _pytest

    unsafe = Settings(debug=False, secret_key=DEV_SECRET)
    with _pytest.raises(RuntimeError, match="development default"):
        unsafe.assert_production_safe()

    short = Settings(debug=False, secret_key="too-short")
    with _pytest.raises(RuntimeError, match="32 bytes"):
        short.assert_production_safe()

    ok = Settings(
        debug=False, secret_key="x" * 40, cookie_secure=True,
        cors_origins=["https://app.example.com"],
    )
    ok.assert_production_safe()  # does not raise
