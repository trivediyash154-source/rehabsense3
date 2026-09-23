"""The Live Lab's sensor source.

The simulator is started as an ordinary client of `/ws/ingest`, so these also
guard the rule that the UI gets no privileged ingestion shortcut.
"""

from __future__ import annotations

import time


def _session(client, clinician, patient_record):
    return client.post(
        "/api/sessions",
        json={"patient_id": patient_record["id"], "exercise_type": "WALK"},
        headers=clinician["headers"],
    ).json()


def test_simulate_requires_authentication(client, clinician, patient_record):
    session = _session(client, clinician, patient_record)
    # The shared test client keeps the fixture's session cookie; drop it so the
    # request is genuinely anonymous.
    client.cookies.clear()
    try:
        r = client.post(f"/api/sessions/{session['id']}/simulate", json={})
        assert r.status_code == 401, r.text
    finally:
        client.delete(f"/api/sessions/{session['id']}/simulate", headers=clinician["headers"])


def test_simulate_rejects_an_unknown_scenario(client, clinician, patient_record):
    session = _session(client, clinician, patient_record)
    r = client.post(f"/api/sessions/{session['id']}/simulate",
                    json={"scenario": "NOT_A_SCENARIO"}, headers=clinician["headers"])
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_simulate_bounds_the_duration(client, clinician, patient_record):
    session = _session(client, clinician, patient_record)
    for duration in (1, 100_000):
        r = client.post(f"/api/sessions/{session['id']}/simulate",
                        json={"duration_s": duration}, headers=clinician["headers"])
        assert r.status_code == 422, f"duration {duration} should be refused"


def test_a_second_stream_is_refused_with_conflict(client, clinician, patient_record):
    """Regression: this raised NameError -> 500 instead of a typed 409."""
    session = _session(client, clinician, patient_record)
    first = client.post(f"/api/sessions/{session['id']}/simulate",
                        json={"scenario": "ASYMMETRY", "duration_s": 5},
                        headers=clinician["headers"])
    assert first.status_code == 200, first.text
    try:
        second = client.post(f"/api/sessions/{session['id']}/simulate",
                             json={"scenario": "ASYMMETRY", "duration_s": 5},
                             headers=clinician["headers"])
        assert second.status_code == 409, second.text
        assert second.json()["code"] == "CONFLICT"
    finally:
        client.delete(f"/api/sessions/{session['id']}/simulate", headers=clinician["headers"])


def test_stopping_a_stream_that_is_not_running_is_safe(client, clinician, patient_record):
    session = _session(client, clinician, patient_record)
    r = client.delete(f"/api/sessions/{session['id']}/simulate", headers=clinician["headers"])
    assert r.status_code == 204


def test_simulate_refuses_a_completed_session(client, clinician, patient_record):
    session = _session(client, clinician, patient_record)
    client.post(f"/api/sessions/{session['id']}/end", json={}, headers=clinician["headers"])
    r = client.post(f"/api/sessions/{session['id']}/simulate", json={},
                    headers=clinician["headers"])
    assert r.status_code == 409


def test_another_clinician_cannot_stream_into_this_session(client, clinician, patient_record):
    import uuid

    session = _session(client, clinician, patient_record)
    email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/signup", json={
        "email": email, "password": "a-very-long-passphrase",
        "name": "Other Clinician", "role": "PHYSIOTHERAPIST"})
    pair = client.post("/api/auth/token", json={
        "email": email, "password": "a-very-long-passphrase"}).json()
    headers = {"Authorization": f"Bearer {pair['access_token']}"}

    r = client.post(f"/api/sessions/{session['id']}/simulate", json={}, headers=headers)
    # 404, not 403: the session's existence is not confirmed to a stranger.
    assert r.status_code == 404
