"""End-to-end: one dual-IMU device through the real v2 socket to the API.

    simulated ESP32 packet -> /ws/ingest/v2 -> validation -> stream integrity
    -> calibration -> windows -> analytics -> PostgreSQL/SQLite rows
    -> /ws/live broadcast -> REST analysis -> session end summary

This is the test that must keep passing when the real ESP32 + 2x MPU6050 +
force hardware is connected: the firmware speaks exactly this protocol.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.simulator.dual_imu import DualImuModel, SideConfig

RATE = 100.0
BATCH = 10


def _hello(*, simulated=True, force=True, right=True, device_id="esp32-dual-test", key=None):
    imus = [{"side": "LEFT", "placement": "SHANK", "i2c_address": "0x68"}]
    if right:
        imus.append({"side": "RIGHT", "placement": "SHANK", "i2c_address": "0x69"})
    hello = {
        "type": "hello", "protocol_version": 2, "device_id": device_id,
        "firmware_version": "test-2.0", "sample_rate_hz": RATE, "imus": imus,
        "force_channels": [{"id": "heel_left", "side": "LEFT"},
                           {"id": "heel_right", "side": "RIGHT"}] if force else [],
        "simulated": simulated,
    }
    if key:
        hello["device_key"] = key
    return hello


def _flush(ws) -> None:
    """Packets are processed in order, so a pong means all prior data landed."""
    ws.send_json({"type": "ping"})
    while ws.receive_json()["type"] != "pong":
        pass


def _stream(ws, model: DualImuModel, seconds: float, seq0: int = 0) -> list[dict]:
    sent = []
    batch = []
    for i in range(seq0, seq0 + int(seconds * RATE)):
        s = {"ts": round(i / RATE, 4), "seq": i, **model.sample(i / RATE)}
        batch.append(s)
        sent.append(s)
        if len(batch) == BATCH:
            ws.send_json({"type": "data", "samples": batch})
            batch = []
    if batch:
        ws.send_json({"type": "data", "samples": batch})
    _flush(ws)
    return sent


def _ticket(client, clinician, session_id):
    r = client.post("/api/auth/ws-ticket", json={"session_id": session_id},
                    headers=clinician["headers"])
    assert r.status_code == 200, r.text
    return r.json()["ticket"]


@pytest.fixture
def squat_session(client, clinician, patient_record):
    r = client.post("/api/sessions", headers=clinician["headers"],
                    json={"patient_id": patient_record["id"], "exercise_type": "SQUAT"})
    assert r.status_code == 201, r.text
    return r.json()


def test_dual_imu_pipeline_end_to_end(client, clinician, squat_session):
    sid = squat_session["id"]
    headers = clinician["headers"]
    model = DualImuModel(exercise="SQUAT", seed=4, left=SideConfig(severity=0.4))

    with client.websocket_connect(f"/ws/live/{sid}?ticket={_ticket(client, clinician, sid)}") as dash:
        assert dash.receive_json()["type"] == "session_status"

        with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
            dev.send_json(_hello())
            ack = dev.receive_json()
            assert ack["type"] == "hello_ack" and ack["protocol_version"] == 2
            assert ack["accepted_imus"] == ["LEFT", "RIGHT"]
            assert ack["accepted_force_channels"] == ["heel_left", "heel_right"]

            # One malformed packet must not end the session.
            dev.send_json({"type": "data", "samples": [{"ts": "x", "seq": 0}]})
            assert dev.receive_json()["code"] == "INVALID_SENSOR_PACKET"

            sent = _stream(dev, model, 40.0)
            # A retransmitted packet is dropped as duplicates, not double counted.
            dev.send_json({"type": "data", "samples": sent[-10:]})
            dev.send_json({"type": "status", "battery_pct": 77.0, "imu_left_ok": True,
                           "imu_right_ok": True})
            _flush(dev)

        # The dashboard received hardware events (drain what is buffered).
        seen = set()
        for _ in range(4000):
            msg = dash.receive_json()
            seen.add(msg["type"])
            if {"hw_calibration", "hw_sensor_frame", "hw_ml_update", "hw_rep",
                    "hw_connection"} <= seen:
                break
        assert {"hw_calibration", "hw_sensor_frame", "hw_ml_update", "hw_rep",
                "hw_connection"} <= seen

    # ---- calibration persisted with all eight checks ---- #
    cal = client.get(f"/api/sessions/{sid}/calibration", headers=headers).json()["items"]
    assert len(cal) == 1 and cal[0]["simulated"] is True
    assert len(cal[0]["metadata"]["checks"]) == 8
    assert cal[0]["status"] == "PASS"

    # ---- raw samples stored, decodable, byte-for-byte the values sent ---- #
    # The last partial (< 1 s) chunk is flushed by the server's disconnect
    # handler, which runs asynchronously after the client closes the socket.
    import time as _t

    for _ in range(50):
        rec = client.get(f"/api/sessions/{sid}/recording", headers=headers).json()
        if rec["samples"] == len(sent):
            break
        _t.sleep(0.05)
    assert rec["samples"] == len(sent) and rec["simulated"] is True
    from app.db.database import SessionLocal
    from app.services import sensing_service

    db = SessionLocal()
    try:
        cols, data = sensing_service.session_samples(db, sid)
    finally:
        db.close()
    assert cols[:4] == ["t", "seq", "left_ax", "left_ay"]
    assert data[:, 1].astype(int).tolist() == list(range(len(sent)))
    assert np.allclose(data[100, 2:8], [sent[100]["imu_left"][k] for k in
                                        ("ax", "ay", "az", "gx", "gy", "gz")], atol=1e-4)
    csv = client.get(f"/api/sessions/{sid}/recording.csv", headers=headers)
    assert csv.status_code == 200 and "left_ax" in csv.text

    # ---- activity: no model loaded in tests -> says so, never guesses ---- #
    act = client.get(f"/api/sessions/{sid}/activity", headers=headers).json()
    assert act["windows"] and all(w["status"] == "MODEL_UNAVAILABLE" for w in act["windows"])
    assert all(w["activity"] is None for w in act["windows"])

    # ---- end the session: v2 summary is authoritative ---- #
    ended = client.post(f"/api/sessions/{sid}/end", headers=headers, json={}).json()
    assert ended["status"] == "COMPLETED" and ended["mode"] == "SIMULATED"
    s = ended["summary"]
    assert s["protocol_version"] == 2
    assert s["stream"]["duplicates"] == 10
    assert s["repetitions"] >= 16
    assert s["bilateral"]["status"] == "OK"
    assert 0.1 < s["bilateral"]["asymmetry_score"] < 0.5
    assert s["movement_quality"]["mqi"] is not None
    assert "NOT CLINICALLY VALIDATED" in s["movement_quality"]["label"]
    assert s["force_motion"]["status"] == "OK"
    assert s["validation"] == {**s["validation"], "rehabsense_hardware": "NOT_VALIDATED",
                               "clinical": "NOT_VALIDATED"}
    # Not computable from one IMU per leg: null, not approximated.
    assert s["rom_deg"] is None and s["symmetry_index_pct"] is None
    assert "inference" in s["latency"] and "db_write" in s["latency"]

    # ---- analysis endpoint reads the persisted rows ---- #
    analysis = client.get(f"/api/sessions/{sid}/analysis", headers=headers).json()
    assert analysis["protocol_version"] == 2
    sides = {r["side"] for r in analysis["repetitions"]}
    assert sides == {"LEFT", "RIGHT"}
    assert analysis["session_assessment"]["mqi"] == s["movement_quality"]["mqi"]

    # v1 surfaces still work on a v2 session (nulls, not crashes).
    assert client.get(f"/api/sessions/{sid}/report", headers=headers).status_code == 200

    # ---- labels ---- #
    lab = client.post(f"/api/sessions/{sid}/labels", headers=headers, json={
        "t_start": 10.0, "t_end": 13.0, "exercise_type": "SQUAT", "repetition_index": 2,
        "side": "LEFT", "movement_phase": "movement", "quality_rating": 3})
    assert lab.status_code == 201, lab.text
    bad = client.post(f"/api/sessions/{sid}/labels", headers=headers,
                      json={"t_start": 5, "t_end": 4})
    assert bad.status_code == 422
    assert len(client.get(f"/api/sessions/{sid}/labels", headers=headers).json()["items"]) == 1

    # ---- a SIMULATED session can never become a patient's baseline ---- #
    pid = ended["patient_id"]
    r = client.post(f"/api/patients/{pid}/baseline", headers=headers, json={"session_ids": [sid]})
    assert r.status_code == 400 and "SIMULATED" in r.json()["message"]


def _technician(client):
    """A technician account (device registration role), promoted in the DB."""
    import uuid

    from app.db.database import SessionLocal
    from app.db.models.user import Role, User

    email = f"tech-{uuid.uuid4().hex[:6]}@example.com"
    client.post("/api/auth/signup", json={"email": email, "password": "a-very-long-passphrase",
                                          "name": "Tech", "role": "PATIENT"})
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(email=email).one()
        u.role = Role.TECHNICIAN
        db.commit()
    finally:
        db.close()
    tok = client.post("/api/auth/token", json={"email": email,
                                                "password": "a-very-long-passphrase"}).json()
    return {"Authorization": f"Bearer {tok['access_token']}"}


def _register(client, device_id):
    r = client.post("/api/devices/register", headers=_technician(client),
                    json={"device_id": device_id, "notes": "bench unit"})
    assert r.status_code == 201, r.text
    return r.json()["device_key"]


def test_unregistered_non_simulated_device_is_unverified_not_live(client, clinician, squat_session):
    sid, headers = squat_session["id"], clinician["headers"]
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=False, device_id="esp32-unregistered"))
        assert dev.receive_json()["type"] == "hello_ack"
        _stream(dev, DualImuModel(exercise="SQUAT", seed=1), 3.0)
    s = client.get(f"/api/sessions/{sid}", headers=headers).json()
    assert s["mode"] == "UNVERIFIED"
    v = client.get(f"/api/sessions/{sid}/validation", headers=headers).json()
    assert v["data_source"] == "PHYSICAL_UNVERIFIED" and v["counts_as_hardware_evidence"] is False
    dev_row = next(d for d in client.get("/api/devices", headers=headers).json()["items"]
                   if d["device_id"] == "esp32-unregistered")
    assert dev_row["kind"] == "UNVERIFIED" and dev_row["verified_hardware"] is False


def test_registered_device_must_present_its_own_key(client, clinician, squat_session):
    sid = squat_session["id"]
    key = _register(client, "esp32-bench-01")
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=False, device_id="esp32-bench-01", key="wrong"))
        assert dev.receive_json()["code"] == "DEVICE_UNAUTHORIZED"
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=True, device_id="esp32-bench-01", key=key))
        assert dev.receive_json()["code"] == "REGISTERED_DEVICE_DECLARED_SIMULATED"
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=False, device_id="esp32-bench-01", key=key))
        assert dev.receive_json()["type"] == "hello_ack"
    s = client.get(f"/api/sessions/{sid}", headers=clinician["headers"]).json()
    assert s["mode"] == "LIVE"


def test_only_clinicians_cannot_register_devices(client, clinician):
    r = client.post("/api/devices/register", headers=clinician["headers"],
                    json={"device_id": "x-1"})
    assert r.status_code == 403


def test_consent_retains_only_verified_hardware(client, clinician, patient_record, squat_session):
    sid, pid, headers = squat_session["id"], patient_record["id"], clinician["headers"]
    key = _register(client, "esp32-consent-01")
    model = DualImuModel(exercise="SQUAT", seed=1)
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=False, device_id="esp32-consent-01", key=key))
        assert dev.receive_json()["type"] == "hello_ack"
        _stream(dev, model, 5.0)
    assert client.get(f"/api/patients/{pid}/consent", headers=headers).json()["granted"] is False
    on = client.put(f"/api/patients/{pid}/consent", headers=headers,
                    json={"granted": True, "document_ref": "consent-form-17"}).json()
    assert on["granted"] is True
    rec = client.get(f"/api/sessions/{sid}/recording", headers=headers).json()
    assert rec["retained_for_training_chunks"] == rec["chunks"] > 0
    off = client.put(f"/api/patients/{pid}/consent", headers=headers, json={"granted": False}).json()
    assert off["granted"] is False
    rec = client.get(f"/api/sessions/{sid}/recording", headers=headers).json()
    assert rec["retained_for_training_chunks"] == 0


def test_single_imu_device_reports_single_side(client, clinician, squat_session):
    sid, headers = squat_session["id"], clinician["headers"]
    model = DualImuModel(exercise="SQUAT", seed=2, right=SideConfig(present=False))
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(right=False))
        assert dev.receive_json()["accepted_imus"] == ["LEFT"]
        _stream(dev, model, 25.0)
    s = client.post(f"/api/sessions/{sid}/end", headers=headers, json={}).json()["summary"]
    assert s["bilateral"]["asymmetry_score"] is None
    assert s["repetition_summary"].keys() == {"LEFT"}


def test_protocols_cannot_mix_in_one_session(client, squat_session):
    sid = squat_session["id"]
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello())
        assert dev.receive_json()["type"] == "hello_ack"
        with client.websocket_connect(f"/ws/ingest/{sid}?leg=LEFT") as v1:
            err = v1.receive_json()
            assert err["code"] == "SESSION_PROTOCOL_CONFLICT"
        with client.websocket_connect(f"/ws/ingest/v2/{sid}") as second:
            second.send_json(_hello())
            assert second.receive_json()["code"] == "DEVICE_ALREADY_ATTACHED"


def test_device_key_and_simulation_switch(client, squat_session, monkeypatch):
    from app.core.config import get_settings

    sid = squat_session["id"]
    settings = get_settings()
    monkeypatch.setattr(settings, "device_ingest_key", "s3cret-device-key")
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(key="wrong"))
        assert dev.receive_json()["code"] == "DEVICE_UNAUTHORIZED"
    monkeypatch.setattr(settings, "device_ingest_key", None)
    monkeypatch.setattr(settings, "allow_simulated_devices", False)
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=True))
        assert dev.receive_json()["code"] == "SIMULATION_DISABLED"


def test_v2_endpoints_hide_other_patients_sessions(client, squat_session):
    """A different clinician gets 404, not 403, on every new route."""
    import uuid

    email = f"other-{uuid.uuid4().hex[:6]}@example.com"
    client.post("/api/auth/signup", json={"email": email, "password": "a-very-long-passphrase",
                                          "name": "Other", "role": "PHYSIOTHERAPIST"})
    token = client.post("/api/auth/token", json={"email": email,
                                                  "password": "a-very-long-passphrase"}).json()
    h = {"Authorization": f"Bearer {token['access_token']}"}
    sid = squat_session["id"]
    for path in ("analysis", "activity", "calibration", "recording", "labels"):
        assert client.get(f"/api/sessions/{sid}/{path}", headers=h).status_code == 404, path
    assert client.get(f"/api/patients/{squat_session['patient_id']}/consent",
                      headers=h).status_code == 404


def test_retention_purges_only_expired_unretained_chunks(db):
    from datetime import datetime, timedelta, timezone

    from app.db.models.sensing import SensorSampleChunk
    from app.services import sensing_service

    now = datetime.now(timezone.utc)
    from app.db.models.patient import Leg, PatientProfile
    from app.db.models.session import ExerciseType, Session as S

    p = PatientProfile(name="R", operated_leg=Leg.LEFT)
    db.add(p)
    db.flush()
    s = S(patient_id=p.id, exercise_type=ExerciseType.SQUAT, started_at=now)
    db.add(s)
    db.flush()
    for i, (expires, retain) in enumerate([(now - timedelta(days=1), False),
                                           (now - timedelta(days=1), True),
                                           (now + timedelta(days=5), False)]):
        db.add(SensorSampleChunk(session_id=s.id, chunk_index=i, t_start=0, t_end=1, n_samples=1,
                                 columns=["t"], encoding="float32-le-zlib", data=b"x",
                                 expires_at=expires, retain_for_training=retain, created_at=now))
    db.flush()
    assert sensing_service.purge_expired_chunks(db, now) == 1


def test_device_is_told_when_the_session_ends(client, clinician, squat_session):
    sid, headers = squat_session["id"], clinician["headers"]
    model = DualImuModel(exercise="SQUAT", seed=3)
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello())
        assert dev.receive_json()["type"] == "hello_ack"
        _stream(dev, model, 4.0)
        assert client.post(f"/api/sessions/{sid}/end", headers=headers, json={}).status_code == 200
        dev.send_json({"type": "data", "samples": [{"ts": 9.0, "seq": 900, **model.sample(9.0)}]})
        assert dev.receive_json()["code"] == "SESSION_ENDED"


def test_validation_mode_flags_abnormal_and_missing_data(client, clinician, squat_session):
    sid, headers = squat_session["id"], clinician["headers"]
    model = DualImuModel(exercise="SQUAT", seed=8)
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello())
        assert dev.receive_json()["type"] == "hello_ack"
        sent = []
        for i in range(1500):
            if 900 <= i < 960:           # 60 lost samples
                continue
            s = {"ts": i / RATE, "seq": i, **model.sample(i / RATE)}
            if i == 1000:                # impossible reading on the right IMU (> +-4 g range)
                s["imu_right"] = {**s["imu_right"], "ax": 9.5}
            sent.append(s)
        for k in range(0, len(sent), 10):
            dev.send_json({"type": "data", "samples": sent[k:k + 10]})
        live = client.get(f"/api/sessions/{sid}/validation", headers=headers).json()
        _flush(dev)
        live = client.get(f"/api/sessions/{sid}/validation", headers=headers).json()
    assert live["live"] is True and live["data_source"] == "SIMULATED"
    checks = {c["key"]: c for c in live["checks"]}
    assert checks["missing_samples"]["value"] > 0
    assert checks["right_abnormal_values"]["status"] == "FAIL"
    assert live["verdict"] == "NOT_USABLE"
    client.post(f"/api/sessions/{sid}/end", headers=headers, json={})
    stored = client.get(f"/api/sessions/{sid}/validation", headers=headers).json()
    assert stored["live"] is False and stored["counts_as_hardware_evidence"] is False
    assert "never physical-device evidence" in stored["evidence_level"]


def test_pilot_status_never_counts_simulated_sessions(client, clinician, squat_session):
    sid, headers = squat_session["id"], clinician["headers"]
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=True))
        assert dev.receive_json()["type"] == "hello_ack"
        _stream(dev, DualImuModel(exercise="SQUAT", seed=1), 3.0)
    client.post(f"/api/sessions/{sid}/end", headers=headers, json={})
    st = client.get("/api/ml/pilot-status", headers=headers).json()
    assert st["real_sessions"] == 0 and st["simulated_sessions_excluded"] >= 1
    assert st["hardware_validation_possible"] is False


def test_calibration_workflow_phases_reach_the_device_and_are_reproducible(client, clinician,
                                                                          squat_session):
    sid, headers = squat_session["id"], clinician["headers"]
    model = DualImuModel(exercise="SQUAT", seed=5)
    phases = []
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello())
        ack = dev.receive_json()
        assert ack["calibration_health_seconds"] == 1.0
        batch = []
        for i in range(int(14 * RATE)):
            batch.append({"ts": i / RATE, "seq": i, **model.sample(i / RATE)})
            if len(batch) == 10:
                dev.send_json({"type": "data", "samples": batch})
                batch = []
        dev.send_json({"type": "ping"})
        while True:
            m = dev.receive_json()
            if m["type"] == "calibration_phase":
                phases.append(m["phase"])
            if m["type"] == "pong":
                break
    assert phases[:4] == ["HEALTH_CHECK", "STILL", "MOVEMENT", "COMPLETE"]
    cal = client.get(f"/api/sessions/{sid}/calibration", headers=headers).json()["items"][0]
    assert cal["sequence"] == 1 and cal["valid"] is True and cal["t_start"] is not None
    w = cal["metadata"]["windows"]
    assert w["still"][1] - w["still"][0] >= 2.9 and w["still"][0] >= 1.0   # after the health check
    from scripts.recompute_calibration import compare

    result = compare(sid, 1)
    assert result["status_recomputed"] == result["status_stored"]
    assert max(result["max_abs_differences"].values()) < 1e-3, result


def test_recalibration_supersedes_and_reconnect_marks_stale(client, clinician, squat_session):
    sid, headers = squat_session["id"], clinician["headers"]
    model = DualImuModel(exercise="SQUAT", seed=6)
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello())
        dev.receive_json()
        _stream(dev, model, 12.0)
    # Reconnect: the strap may have moved -> the calibration is flagged stale.
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello())
        assert dev.receive_json()["type"] == "hello_ack"
        _stream(dev, model, 3.0, seq0=1200)
        v = client.get(f"/api/sessions/{sid}/validation", headers=headers).json()
        cal_check = next(c for c in v["checks"] if c["key"] == "calibration")
        assert cal_check["status"] == "WARN" and "stale" in cal_check["message"]
        assert client.post(f"/api/sessions/{sid}/recalibrate", headers=headers).status_code == 200
        # The wearer stands still again (t 15-20 s), then moves.
        _stream(dev, DualImuModel(exercise="SQUAT", seed=7, still_s=20.0), 12.0, seq0=1500)
    rows = client.get(f"/api/sessions/{sid}/calibration", headers=headers).json()["items"]
    assert [r["sequence"] for r in rows] == [1, 2]
    assert rows[0]["valid"] is False and rows[1]["valid"] is True
    assert rows[0]["invalidation_reason"]


def test_calibration_fails_honestly_when_nobody_holds_still():
    from app.hardware.protocol_v2 import DualSample, HelloV2
    from app.sensing.processor import DualSessionProcessor
    from app.simulator.dual_imu import SideConfig

    h = HelloV2.model_validate(_hello())
    model = DualImuModel(exercise="WALK", still_s=0.0, left=SideConfig(), right=SideConfig())
    proc = DualSessionProcessor(1, "WALK", h)
    proc.on_connect(h)
    for k in range(0, 2600, 10):
        proc.process([DualSample(ts=i / RATE, seq=i, **model.sample(i / RATE)) for i in range(k, k + 10)],
                     arrival=float(k))
    assert proc.calibrator.phase.value == "FAILED"
    assert "no still period" in proc.calibrator.failure_reason
    assert any(a["code"] == "CALIBRATION_FAILED" for a in proc.sensor_alerts())


def test_health_check_retries_on_frozen_sensors_and_never_proceeds():
    from app.hardware.protocol_v2 import DualSample, HelloV2
    from app.sensing.processor import DualSessionProcessor

    h = HelloV2.model_validate(_hello(force=False))
    proc = DualSessionProcessor(1, "SQUAT", h)
    proc.on_connect(h)
    frozen = {"ax": 0.0, "ay": 0.0, "az": 1.0, "gx": 0.0, "gy": 0.0, "gz": 0.0}
    for k in range(0, 500, 10):
        proc.process([DualSample(ts=i / RATE, seq=i, imu_left=frozen, imu_right=frozen)
                      for i in range(k, k + 10)], arrival=float(k))
    c = proc.calibrator
    assert c.phase.value == "HEALTH_CHECK" and c.health_attempts >= 3
    assert {v["reason"] for v in c.health.values()} == {"FROZEN"}


def test_research_recording_requires_consent_and_retains_only_verified_hardware(
        client, clinician, patient_record):
    pid, headers = patient_record["id"], clinician["headers"]
    body = {"patient_id": pid, "exercise_type": "SQUAT", "subject_code": "P01", "task": "squat x10"}
    r = client.post("/api/research/recordings", headers=headers, json=body)
    assert r.status_code == 409 and "consent" in r.json()["message"]
    client.put(f"/api/patients/{pid}/consent", headers=headers,
               json={"granted": True, "document_ref": "form-2"})

    # Unregistered device: recorded, but UNVERIFIED and not retained.
    sid = client.post("/api/research/recordings", headers=headers, json=body).json()["session_id"]
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=False, device_id="esp32-unreg-r"))
        dev.receive_json()
        _stream(dev, DualImuModel(exercise="SQUAT", seed=2), 3.0)
    rec = client.get(f"/api/sessions/{sid}/recording", headers=headers).json()
    assert rec["retained_for_training_chunks"] == 0

    # Registered device: retained, never expires, markers on the device clock.
    key = _register(client, "esp32-research-01")
    sid = client.post("/api/research/recordings", headers=headers, json=body).json()["session_id"]
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=False, device_id="esp32-research-01", key=key))
        dev.receive_json()
        _stream(dev, DualImuModel(exercise="SQUAT", seed=2), 4.0)
        m = client.post(f"/api/sessions/{sid}/markers", headers=headers,
                        json={"label": "rep_start", "note": "first rep"}).json()
        # Mapped from server receive time onto DEVICE_TIME, with uncertainty.
        assert m["t_session"] >= 3.99 and m["t_uncertainty_s"] > 0
    rec = client.get(f"/api/sessions/{sid}/recording", headers=headers).json()
    assert rec["retained_for_training_chunks"] == rec["chunks"] > 0 and rec["earliest_expiry"] is None
    rr = client.get(f"/api/sessions/{sid}/research-record", headers=headers).json()
    assert rr["recording_mode"] == "RESEARCH" and rr["provenance"] == "PHYSICAL_REGISTERED"
    assert rr["research_protocol"]["subject_code"] == "P01"
    user = [m for m in rr["markers"] if m["source"] == "USER"]
    assert user[0]["label"] == "rep_start" and user[0]["time_basis"] == "SERVER_RECEIVE_TIME_MAPPED"
    assert rr["markers"][0]["kind"] == "recording_start" and rr["markers"][0]["source"] == "SERVER"
    assert rr["recording"]["samples"] == 400
