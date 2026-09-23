"""Authorisation isolation.

The frontend's role toggle is a convenience. These tests assert the server
enforces access independently, so a crafted request cannot reach another
person's health data.
"""

from __future__ import annotations

import uuid

import pytest


def _register(client, role):
    email = f"{role.lower()}-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/signup", json={
        "email": email, "password": "a-very-long-passphrase", "name": "Test", "role": role,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    pair = client.post("/api/auth/token", json={
        "email": email, "password": "a-very-long-passphrase"}).json()
    return {"headers": {"Authorization": f"Bearer {pair['access_token']}"},
            "id": body["user"]["id"], "email": email}


@pytest.fixture
def two_clinics(client, db):
    """Two clinicians, each with their own patient and a completed session."""
    from app.db.models.patient import PatientProfile

    out = {}
    for key in ("a", "b"):
        clin = _register(client, "PHYSIOTHERAPIST")
        patient = client.post("/api/patients", headers=clin["headers"], json={
            "name": f"Patient {key.upper()}", "operated_leg": "LEFT",
            "notes": f"private note {key}",
        }).json()
        session = client.post("/api/sessions", headers=clin["headers"], json={
            "patient_id": patient["id"], "exercise_type": "SQUAT",
        }).json()
        client.post(f"/api/sessions/{session['id']}/end",
                    headers=clin["headers"], json={})
        out[key] = {"clinician": clin, "patient": patient, "session": session}
    return out


def test_clinician_cannot_read_another_clinics_patient(client, two_clinics):
    a, b = two_clinics["a"], two_clinics["b"]
    r = client.get(f"/api/patients/{b['patient']['id']}", headers=a["clinician"]["headers"])
    # 404 rather than 403: the API must not confirm the record exists.
    assert r.status_code == 404
    assert r.json()["code"] == "PATIENT_NOT_FOUND"


def test_clinician_cannot_read_another_clinics_session(client, two_clinics):
    a, b = two_clinics["a"], two_clinics["b"]
    for path in ("", "/metrics", "/reps", "/report", "/replay"):
        r = client.get(f"/api/sessions/{b['session']['id']}{path}",
                       headers=a["clinician"]["headers"])
        assert r.status_code == 404, f"{path} leaked"


def test_clinician_cannot_read_another_clinics_progress(client, two_clinics):
    a, b = two_clinics["a"], two_clinics["b"]
    for path in ("overview", "progress", "timeline", "passport", "progress/compare"):
        r = client.get(f"/api/patients/{b['patient']['id']}/{path}",
                       headers=a["clinician"]["headers"])
        assert r.status_code == 404, f"{path} leaked"


def test_clinician_cannot_start_a_session_for_another_clinics_patient(client, two_clinics):
    a, b = two_clinics["a"], two_clinics["b"]
    r = client.post("/api/sessions", headers=a["clinician"]["headers"], json={
        "patient_id": b["patient"]["id"], "exercise_type": "SQUAT",
    })
    assert r.status_code == 404


def test_clinician_cannot_edit_another_clinics_patient(client, two_clinics):
    a, b = two_clinics["a"], two_clinics["b"]
    r = client.patch(f"/api/patients/{b['patient']['id']}",
                     headers=a["clinician"]["headers"], json={"notes": "injected"})
    assert r.status_code == 404


def test_patient_cannot_read_another_patients_record(client, two_clinics, db):
    from app.db.models.patient import PatientProfile

    patient_user = _register(client, "PATIENT")
    own = db.get(PatientProfile, two_clinics["a"]["patient"]["id"])
    own.user_id = patient_user["id"]
    db.commit()

    # Their own record: allowed.
    assert client.get(f"/api/patients/{own.id}", headers=patient_user["headers"]).status_code == 200
    # Someone else's: not found.
    other = two_clinics["b"]["patient"]["id"]
    assert client.get(f"/api/patients/{other}", headers=patient_user["headers"]).status_code == 404


def test_patient_listing_excludes_other_peoples_records(client, two_clinics, db):
    from app.db.models.patient import PatientProfile

    patient_user = _register(client, "PATIENT")
    own = db.get(PatientProfile, two_clinics["a"]["patient"]["id"])
    own.user_id = patient_user["id"]
    db.commit()

    listing = client.get("/api/patients", headers=patient_user["headers"]).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == own.id


def test_technician_has_no_access_to_patient_records(client, two_clinics):
    tech = _register(client, "TECHNICIAN")
    listing = client.get("/api/patients", headers=tech["headers"]).json()
    assert listing["total"] == 0
    r = client.get(f"/api/patients/{two_clinics['a']['patient']['id']}", headers=tech["headers"])
    assert r.status_code == 404
    # Devices are a technician's domain, and remain reachable.
    assert client.get("/api/devices", headers=tech["headers"]).status_code == 200


def test_signal_diagnostics_are_clinician_only(client, two_clinics, db):
    from app.db.models.patient import PatientProfile

    patient_user = _register(client, "PATIENT")
    own = db.get(PatientProfile, two_clinics["a"]["patient"]["id"])
    own.user_id = patient_user["id"]
    db.commit()

    session_id = two_clinics["a"]["session"]["id"]
    as_patient = client.get(f"/api/sessions/{session_id}",
                            headers=patient_user["headers"]).json()
    as_clinician = client.get(f"/api/sessions/{session_id}",
                              headers=two_clinics["a"]["clinician"]["headers"]).json()

    assert as_patient["data_quality"] is None
    assert as_clinician["data_quality"] is not None

    patient_report = client.get(f"/api/sessions/{session_id}/report",
                                headers=patient_user["headers"]).json()
    clinician_report = client.get(f"/api/sessions/{session_id}/report",
                                  headers=two_clinics["a"]["clinician"]["headers"]).json()
    assert "clinical" not in patient_report
    assert "clinical" in clinician_report
    # The private note must never appear in the patient-facing payload.
    assert "private note a" not in str(patient_report)


def test_expired_or_tampered_tokens_are_refused(client, two_clinics):
    good = two_clinics["a"]["clinician"]["headers"]["Authorization"]
    tampered = good[:-4] + "AAAA"
    r = client.get("/api/me", headers={"Authorization": tampered})
    assert r.status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_audit_trail_records_sensitive_actions(client, two_clinics, db):
    from sqlalchemy import select
    from app.db.models.audit import AuditAction, AuditLog

    actions = set(db.execute(select(AuditLog.action)).scalars())
    assert AuditAction.PATIENT_CREATED in actions
    assert AuditAction.SESSION_STARTED in actions
    assert AuditAction.SESSION_ENDED in actions

    # Audit rows carry identifiers, never note bodies.
    rows = db.execute(select(AuditLog)).scalars().all()
    assert all("private note" not in str(r.context) for r in rows)
