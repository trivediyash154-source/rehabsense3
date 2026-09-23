"""End-to-end hardware integration.

Two simulated leg nodes speak the production ingestion protocol through the
real WebSocket endpoint. Everything downstream — calibration, fusion,
segmentation, symmetry, scoring, persistence, live broadcast, the REST API
and the generated report — is exercised exactly as real ESP32 firmware would
exercise it.

This is the test that must keep passing when the boards arrive.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from app.simulator.movement import LimbModel


def _ticket(client, clinician, session_id: int) -> str:
    """A live-socket ticket, obtained the way the real dashboard obtains one.

    The live socket is not open to anyone who guesses a session id; it takes a
    short-lived ticket that the API only issues to a caller already permitted
    to read that session.
    """
    response = client.post(
        "/api/auth/ws-ticket",
        json={"session_id": session_id},
        headers=clinician["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()["ticket"]

RATE = 100.0
DT = 1.0 / RATE
BATCH = 10


def _hello(leg: str, *, simulated=True, capabilities=None, protocol=1) -> dict:
    return {
        "type": "hello",
        "protocol_version": protocol,
        "device_id": f"esp32-{leg.lower()}-01",
        "leg": leg,
        "firmware_version": "0.1.0",
        "sensors": capabilities if capabilities is not None else ["thigh_imu", "shin_imu"],
        "simulated": simulated,
    }


def _stream(ws, leg: str, model: LimbModel, *, start: float, end: float, seq_start: int,
            fsr: bool = False) -> int:
    """Push samples the way firmware would: batched, sequence-numbered."""
    seq = seq_start
    t = start
    batch = []
    while t < end:
        if t < 2.6:
            thigh, shin = model.still_imu()   # calibration window
            pressure = 1.0
        else:
            mt = t - 2.6
            thigh, shin = model.imu(mt, DT)
            pressure = 1.0 if model.stance(mt) else 0.02
        sample = {"ts": round(t, 4), "seq": seq, "thigh": thigh, "shin": shin}
        if fsr:
            sample["fsr"] = pressure
        batch.append(sample)
        seq += 1
        t += DT
        if len(batch) >= BATCH:
            ws.send_json({"type": "data", "leg": leg, "seq": seq, "samples": batch})
            batch = []
    if batch:
        ws.send_json({"type": "data", "leg": leg, "seq": seq, "samples": batch})
    return seq


@pytest.fixture
def live_session(client, clinician, patient_record):
    response = client.post(
        "/api/sessions", headers=clinician["headers"],
        json={"patient_id": patient_record["id"], "exercise_type": "SQUAT"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_full_pipeline_from_two_nodes_to_report(client, clinician, live_session):
    session_id = live_session["id"]
    headers = clinician["headers"]

    # A dashboard is watching before any device connects.
    with client.websocket_connect(f"/ws/live/{session_id}?ticket={_ticket(client, clinician, session_id)}") as dashboard:
        first = dashboard.receive_json()
        assert first["type"] == "session_status"

        left_model = LimbModel("SQUAT", severity=0.4, rng=random.Random(11))
        right_model = LimbModel("SQUAT", severity=0.0, rng=random.Random(22))

        # ---- 1. handshake accepted, both nodes ---- #
        with client.websocket_connect(f"/ws/ingest/{session_id}?leg=LEFT") as left, \
             client.websocket_connect(f"/ws/ingest/{session_id}?leg=RIGHT") as right:

            left.send_json(_hello("LEFT"))
            ack_l = left.receive_json()
            right.send_json(_hello("RIGHT", capabilities=["thigh_imu", "shin_imu", "fsr"]))
            ack_r = right.receive_json()

            assert ack_l["type"] == "hello_ack"
            assert ack_l["session_id"] == session_id
            assert ack_l["sample_rate_hz"] == 100.0
            # Capability negotiation echoes what the node declared.
            assert "fsr" in ack_r["accepted_capabilities"]
            assert "fsr" not in ack_l["accepted_capabilities"]

            # ---- 2. calibration then movement ---- #
            _stream(left, "LEFT", left_model, start=0.0, end=26.0, seq_start=0)
            _stream(right, "RIGHT", right_model, start=0.0, end=26.0, seq_start=0, fsr=True)

    # ---- 3. device registration ---- #
    devices = client.get("/api/devices", headers=headers).json()["items"]
    by_id = {d["device_id"]: d for d in devices}
    assert "esp32-left-01" in by_id and "esp32-right-01" in by_id
    # Declared simulated, so recorded as such — never guessed.
    assert by_id["esp32-left-01"]["kind"] == "SIMULATOR"
    right_caps = {s["capability"] for s in by_id["esp32-right-01"]["sensors"]}
    assert right_caps == {"thigh_imu", "shin_imu", "fsr"}

    # ---- 4. metrics were generated and persisted ---- #
    metrics = client.get(f"/api/sessions/{session_id}/metrics", headers=headers).json()
    assert len(metrics) > 5, "expected roughly one snapshot per second"
    assert any(m["left_knee_angle_deg"] is not None for m in metrics)
    assert any(m["right_knee_angle_deg"] is not None for m in metrics)

    # ---- 5. repetitions were segmented on both limbs ---- #
    reps = client.get(f"/api/sessions/{session_id}/reps", headers=headers).json()
    assert len(reps) >= 4
    legs = {r["leg"] for r in reps}
    assert legs == {"LEFT", "RIGHT"}
    # ROM comes from the whole cycle, so it is substantial, not a boundary value.
    assert all(r["rom_deg"] > 15 for r in reps)

    # ---- 6/7/8. end the session: symmetry, recovery, confidence ---- #
    ended = client.post(f"/api/sessions/{session_id}/end", headers=headers,
                        json={"reported_pain": 2}).json()
    summary = ended["summary"]
    assert ended["status"] == "COMPLETED"
    assert ended["mode"] == "SIMULATED"

    # The restricted left limb should read as asymmetric.
    assert summary["symmetry_index_pct"] is not None
    assert 40 < summary["symmetry_index_pct"] < 95
    assert summary["recovery_score"] > 0
    contributions = {c["key"]: c for c in summary["recovery"]["contributions"]}
    assert set(contributions) == {"rom", "symmetry", "compliance", "cadence", "pain"}
    assert contributions["pain"]["available"] is True  # pain was reported

    confidence = summary["confidence"]
    assert confidence["percent"] > 50
    assert confidence["explanation"]

    # ---- 9. database holds it all ---- #
    detail = client.get(f"/api/sessions/{session_id}", headers=headers).json()
    assert detail["summary"]["rom_deg"] == summary["rom_deg"]

    # ---- 11. report generated from persisted data ---- #
    report = client.get(f"/api/sessions/{session_id}/report", headers=headers).json()
    assert report["metrics"]["rom_deg"] == summary["rom_deg"]
    assert report["metrics"]["symmetry_index_pct"] == summary["symmetry_index_pct"]
    assert report["responsible_use"]
    assert len(report["repetitions"]) == len(reps)

    csv_response = client.get(f"/api/sessions/{session_id}/report.csv", headers=headers)
    assert csv_response.status_code == 200
    assert "decision-support" in csv_response.text

    # ---- 12. frontend-shaped values exist ---- #
    replay = client.get(f"/api/sessions/{session_id}/replay", headers=headers).json()
    assert len(replay["frames"]) == len(metrics)
    assert len(replay["repetitions"]) == len(reps)


def test_one_bad_packet_does_not_kill_the_session(client, live_session):
    """A malformed packet is rejected; the stream continues."""
    session_id = live_session["id"]
    model = LimbModel("SQUAT", severity=0.2, rng=random.Random(5))

    with client.websocket_connect(f"/ws/ingest/{session_id}?leg=LEFT") as ws:
        ws.send_json(_hello("LEFT"))
        assert ws.receive_json()["type"] == "hello_ack"

        ws.send_json({"type": "data", "leg": "LEFT", "samples": [{"ts": 0.0, "thigh": "broken"}]})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "INVALID_SENSOR_PACKET"

        # Same socket keeps working.
        _stream(ws, "LEFT", model, start=0.0, end=6.0, seq_start=0)

    from app.db.database import SessionLocal
    from app.db.models.session import MetricSnapshot
    from sqlalchemy import select

    db = SessionLocal()
    try:
        rows = db.execute(
            select(MetricSnapshot).where(MetricSnapshot.session_id == session_id)
        ).scalars().all()
    finally:
        db.close()
    assert len(rows) > 0, "samples after the bad packet were still processed"


def test_handshake_rejects_unsupported_protocol_version(client, live_session):
    with client.websocket_connect(f"/ws/ingest/{live_session['id']}?leg=LEFT") as ws:
        ws.send_json(_hello("LEFT", protocol=99))
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "INVALID_HANDSHAKE"


def test_ingest_rejects_unknown_session(client):
    with client.websocket_connect("/ws/ingest/999999?leg=LEFT") as ws:
        error = ws.receive_json()
        assert error["code"] == "SESSION_NOT_FOUND"


def test_missing_fsr_falls_back_to_gyro_stance_detection(client, clinician, patient_record):
    """A node without an FSR is normal, not an error."""
    session = client.post("/api/sessions", headers=clinician["headers"],
                          json={"patient_id": patient_record["id"], "exercise_type": "WALK"}).json()
    model = LimbModel("WALK", severity=0.1, rng=random.Random(3))

    with client.websocket_connect(f"/ws/ingest/{session['id']}?leg=LEFT") as ws:
        ws.send_json(_hello("LEFT", capabilities=["thigh_imu", "shin_imu"]))
        ack = ws.receive_json()
        assert "fsr" not in ack["accepted_capabilities"]
        _stream(ws, "LEFT", model, start=0.0, end=14.0, seq_start=0)

    metrics = client.get(f"/api/sessions/{session['id']}/metrics",
                         headers=clinician["headers"]).json()
    assert len(metrics) > 3, "gait pipeline ran without a pressure sensor"


def test_single_limb_session_reports_no_symmetry_rather_than_a_fake_number(
    client, clinician, patient_record
):
    session = client.post("/api/sessions", headers=clinician["headers"],
                          json={"patient_id": patient_record["id"], "exercise_type": "SQUAT"}).json()
    model = LimbModel("SQUAT", severity=0.2, rng=random.Random(9))

    with client.websocket_connect(f"/ws/ingest/{session['id']}?leg=LEFT") as ws:
        ws.send_json(_hello("LEFT"))
        ws.receive_json()
        _stream(ws, "LEFT", model, start=0.0, end=20.0, seq_start=0)

    ended = client.post(f"/api/sessions/{session['id']}/end",
                        headers=clinician["headers"], json={}).json()
    assert ended["summary"]["symmetry_index_pct"] is None
    confidence = ended["summary"]["confidence"]
    assert confidence["bilateral_coverage"] == 0.0
    assert "unavailable" in confidence["explanation"]


def test_reconnect_resumes_the_same_session(client, live_session):
    """A dropped socket pauses that leg; reconnecting continues the session."""
    session_id = live_session["id"]
    model = LimbModel("SQUAT", severity=0.2, rng=random.Random(77))

    with client.websocket_connect(f"/ws/ingest/{session_id}?leg=LEFT") as ws:
        ws.send_json(_hello("LEFT"))
        ws.receive_json()
        seq = _stream(ws, "LEFT", model, start=0.0, end=10.0, seq_start=0)

    # Same session id and leg, brand-new socket.
    with client.websocket_connect(f"/ws/ingest/{session_id}?leg=LEFT") as ws:
        ws.send_json(_hello("LEFT"))
        ack = ws.receive_json()
        assert ack["session_id"] == session_id
        _stream(ws, "LEFT", model, start=10.0, end=20.0, seq_start=seq)

    from app.db.database import SessionLocal
    from app.db.models.session import Session as SessionModel

    db = SessionLocal()
    try:
        row = db.get(SessionModel, session_id)
        assert row.status.value == "ACTIVE", "session survived the disconnect"
    finally:
        db.close()


def test_dashboard_receives_live_events(client, clinician, live_session):
    """Events reach a subscribed dashboard, scoped to its own session."""
    session_id = live_session["id"]
    model = LimbModel("SQUAT", severity=0.3, rng=random.Random(4))

    with client.websocket_connect(f"/ws/live/{session_id}?ticket={_ticket(client, clinician, session_id)}") as dashboard:
        assert dashboard.receive_json()["type"] == "session_status"

        with client.websocket_connect(f"/ws/ingest/{session_id}?leg=LEFT") as ws:
            ws.send_json(_hello("LEFT"))
            ws.receive_json()
            _stream(ws, "LEFT", model, start=0.0, end=12.0, seq_start=0)

        seen = set()
        for _ in range(40):
            try:
                message = dashboard.receive_json()
            except Exception:
                break
            seen.add(message["type"])
            if {"connection_status", "metric_update"} <= seen:
                break

    assert "connection_status" in seen
    assert "metric_update" in seen


# --- malformed traffic ---------------------------------------------------- #

def test_a_corrupt_frame_does_not_end_the_session(client, clinician, live_session):
    """Regression: one non-JSON frame used to close the ingestion socket.

    A node on a weak link can emit a partial write. Losing the whole session
    for one bad frame would make real hardware look far less reliable than it
    is, so a corrupt frame is discarded like any other malformed packet.
    """
    session_id = live_session["id"]
    with client.websocket_connect(f"/ws/ingest/{session_id}?leg=LEFT") as ws:
        ws.send_json({
            "type": "hello", "protocol_version": 1, "device_id": "corrupt-01",
            "leg": "LEFT", "firmware_version": "t", "sensors": ["thigh_imu", "shin_imu"],
        })
        assert ws.receive_json()["type"] == "hello_ack"

        ws.send_text("this is not json at all {[")
        error = ws.receive_json()
        assert error["code"] == "INVALID_SENSOR_PACKET"

        ws.send_text("[1, 2, 3]")  # valid JSON, but not an object
        assert ws.receive_json()["code"] == "INVALID_SENSOR_PACKET"

        # The socket is still usable afterwards.
        ws.send_json({
            "type": "data", "leg": "LEFT",
            "samples": [{
                "ts": i * 0.01, "seq": i,
                "thigh": {"ax": 0.0, "ay": 0.0, "az": 1.0, "gx": 0.0, "gy": 0.0, "gz": 0.0},
                "shin": {"ax": 0.0, "ay": 0.0, "az": 1.0, "gx": 0.0, "gy": 0.0, "gz": 0.0},
            } for i in range(10)],
        })
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_persistently_corrupt_input_is_eventually_disconnected(client, clinician, live_session):
    """A node emitting nothing but rubbish is broken and is cut off."""
    session_id = live_session["id"]
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/ingest/{session_id}?leg=RIGHT") as ws:
            ws.send_json({
                "type": "hello", "protocol_version": 1, "device_id": "junk-01",
                "leg": "RIGHT", "firmware_version": "t", "sensors": ["thigh_imu", "shin_imu"],
            })
            ws.receive_json()
            for _ in range(60):
                ws.send_text("garbage")
                ws.receive_json()
