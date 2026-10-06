"""Research recordings: export, integrity, provenance, labels vs predictions, clocks."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.simulator.dual_imu import DualImuModel, SideConfig
from tests.test_hardware_v2_integration import RATE, _flush, _hello, _register, _stream


def _research(client, headers, pid, code="P07"):
    client.put(f"/api/patients/{pid}/consent", headers=headers, json={"granted": True, "document_ref": "f"})
    return client.post("/api/research/recordings", headers=headers, json={
        "patient_id": pid, "exercise_type": "SQUAT", "subject_code": code}).json()["session_id"]


def _record_physical(client, headers, sid, model, seconds, device_id, mutate=None):
    key = _register(client, device_id)
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(_hello(simulated=False, device_id=device_id, key=key))
        assert dev.receive_json()["type"] == "hello_ack"
        sent, batch = [], []
        for i in range(int(seconds * RATE)):
            s = {"ts": 100.0 + i / RATE, "seq": i, **model.sample(i / RATE)}
            if mutate:
                s = mutate(i, s)
                if s is None:
                    continue
            sent.append(s)
            batch.append(s)
            if len(batch) == 10:
                dev.send_json({"type": "data", "samples": batch, "sent_ts": s["ts"] + 0.002})
                batch = []
        dev.send_json({"type": "event", "ts": 105.0, "kind": "exercise_start", "note": "button"})
        _flush(dev)
    client.post(f"/api/sessions/{sid}/end", headers=headers, json={})
    return sent


def test_research_export_is_complete_hashed_and_raw(client, clinician, patient_record, tmp_path):
    from app.db.database import SessionLocal
    from app.sensing.export import export_recording, verify_export

    pid, headers = patient_record["id"], clinician["headers"]
    sid = _research(client, headers, pid)

    def mutate(i, s):
        if 1200 <= i < 1500:          # right IMU unavailable for 3 s
            s["imu_right"] = None
        if 1500 <= i < 1520:          # 20 samples lost in transit
            return None
        return s

    sent = _record_physical(client, headers, sid, DualImuModel(seed=3), 20.0, "esp32-exp-01", mutate)
    db = SessionLocal()
    try:
        manifest = export_recording(db, sid, tmp_path / "rec")
    finally:
        db.close()
    out = tmp_path / "rec"
    names = {f["name"] for f in manifest["files"]}
    assert {"metadata.json", "samples.npz", "events.json", "labels.json", "predictions.json",
            "calibration.json", "integrity.json", "derived/calibrated.npz"} <= names
    assert manifest["schema_version"] and manifest["provenance"] == "PHYSICAL_REGISTERED"
    assert verify_export(out)["ok"]

    z = np.load(out / "samples.npz")
    assert len(z["t"]) == len(sent) == manifest["sample_counts"]["samples.npz"]
    assert z["seq"].dtype == np.int64 and z["t"].dtype == np.float64
    assert np.allclose(z["device_ts"], [s["ts"] for s in sent])          # exact device clock
    gap = np.flatnonzero(np.diff(z["seq"]) > 1)
    assert len(gap) == 1 and z["seq"][gap[0] + 1] - z["seq"][gap[0]] == 21   # loss kept as a gap
    r = list(z["columns"]).index("right_ax")
    assert np.isnan(z["values"][1200:1500, r:r + 6]).all(), "unavailable stays NaN, never interpolated"
    assert z["values"][100, 0] == pytest.approx(sent[100]["imu_left"]["ax"], abs=1e-5)
    assert len(z["packet_server_receive_unix"]) > 0 and np.isfinite(z["packet_device_sent_ts"]).all()

    meta = json.loads((out / "metadata.json").read_text())
    for key in ("recording_id", "session_id", "device_id", "pseudonymous_subject_code",
                "start_timestamp", "end_timestamp", "duration_s", "firmware_version",
                "protocol_version", "calibration_id", "sampling", "packets", "availability",
                "calibration_status", "consent_model_training", "provenance", "clock"):
        assert key in meta, key
    assert meta["pseudonymous_subject_code"] == "P07" and "Demo Patient" not in json.dumps(meta)
    assert meta["packets"]["missing_samples"] == 20
    assert meta["sampling"]["effective_rate_hz"] < meta["sampling"]["observed_rate_hz_median_interval"]
    assert meta["availability"]["RIGHT"] < 1.0 and meta["availability"]["LEFT"] == 1.0

    events = json.loads((out / "events.json").read_text())["events"]
    kinds = {(e["kind"], e["source"], e["time_basis"]) for e in events}
    assert ("recording_start", "SERVER", "DEVICE_TIME") in kinds
    assert ("calibration_complete", "SERVER", "DEVICE_TIME") in kinds
    assert ("recording_stop", "SERVER", "DEVICE_TIME") in kinds
    dev_ev = next(e for e in events if e["source"] == "DEVICE")
    assert dev_ev["kind"] == "exercise_start" and dev_ev["t_session"] == pytest.approx(5.0)
    fail = [e for e in events if e["kind"] == "sensor_failure" and e["label"] == "RIGHT_IMU_UNAVAILABLE"]
    back = [e for e in events if e["kind"] == "sensor_recovered" and e["label"] == "RIGHT_IMU_UNAVAILABLE"]
    assert fail and back and 12.0 <= fail[0]["t_session"] <= 15.5 <= back[0]["t_session"] + 2.5

    # Tampering is detected.
    with open(out / "samples.npz", "ab") as fh:
        fh.write(b"x")
    assert not verify_export(out)["ok"]


def test_integrity_flags_a_bad_recording_and_never_repairs_it(client, clinician, patient_record):
    from app.db.database import SessionLocal
    from app.services import sensing_service

    pid, headers = patient_record["id"], clinician["headers"]
    sid = _research(client, headers, pid, "P08")

    def mutate(i, s):
        if i == 1300:
            s["imu_left"] = {**s["imu_left"], "gx": 9999.0}   # impossible for +-500 dps
        return s

    _record_physical(client, headers, sid, DualImuModel(seed=4), 15.0, "esp32-int-01", mutate)
    r = client.get(f"/api/sessions/{sid}/recording-integrity", headers=headers).json()
    assert r["integrity_status"] == "FAIL"
    bad = next(c for c in r["integrity"]["checks"] if c["key"] == "no_impossible_values")
    assert bad["status"] == "FAIL"
    db = SessionLocal()
    try:
        cols, data = sensing_service.session_samples(db, sid)
    finally:
        db.close()
    assert data[1300, 2 + cols[2:].index("left_gx")] == pytest.approx(9999.0), "raw evidence kept"


def test_labels_and_predictions_are_never_conflated(client, clinician, patient_record, tmp_path):
    import uuid

    from app.db.database import SessionLocal
    from app.sensing.export import export_recording

    pid, headers = patient_record["id"], clinician["headers"]
    inv = client.get("/api/ml/label-inventory", headers=headers).json()
    assert inv["HUMAN_LABELED_PHYSICAL_RECORDINGS"] == 0
    sid = _research(client, headers, pid, "P09")
    _record_physical(client, headers, sid, DualImuModel(seed=5), 12.0, "esp32-lab-01")
    lab = client.post(f"/api/sessions/{sid}/labels", headers=headers,
                      json={"t_start": 9.0, "t_end": 11.0, "activity": "standing"}).json()
    assert lab["tier"] == "SILVER"
    # The labeller cannot promote their own label to GOLD...
    assert client.post(f"/api/sessions/{sid}/labels/{lab['id']}/confirm",
                       headers=headers).status_code == 409
    # ...a second clinician assigned to the patient can.
    email = f"c2-{uuid.uuid4().hex[:6]}@example.com"
    client.post("/api/auth/signup", json={"email": email, "password": "a-very-long-passphrase",
                                          "name": "C2", "role": "PHYSIOTHERAPIST"})
    tok = client.post("/api/auth/token", json={"email": email, "password": "a-very-long-passphrase"}).json()
    h2 = {"Authorization": f"Bearer {tok['access_token']}"}
    from app.db.database import SessionLocal as SL
    from app.db.models.patient import PatientAssignment
    from app.db.models.user import User

    db = SL()
    try:
        db.add(PatientAssignment(patient_id=pid, clinician_id=db.query(User).filter_by(email=email).one().id))
        db.commit()
    finally:
        db.close()
    gold = client.post(f"/api/sessions/{sid}/labels/{lab['id']}/confirm", headers=h2).json()
    assert gold["tier"] == "GOLD"
    inv = client.get("/api/ml/label-inventory", headers=headers).json()
    assert inv["HUMAN_LABELED_PHYSICAL_RECORDINGS"] == 1 and inv["GOLD_PHYSICAL_RECORDINGS"] == 1

    db = SessionLocal()
    try:
        export_recording(db, sid, tmp_path / "r")
    finally:
        db.close()
    labels = json.loads((tmp_path / "r" / "labels.json").read_text())
    preds = json.loads((tmp_path / "r" / "predictions.json").read_text())
    assert labels["kind"] == "HUMAN_LABEL" and preds["kind"] == "MODEL_PREDICTION"
    assert [l["activity"] for l in labels["labels"]] == ["standing"]
    assert all("prediction" in p and "activity" not in p for p in preds["activity"])


def test_replay_provenance_and_newtons_need_calibration():
    from app.hardware.protocol_v2 import HelloV2

    h = HelloV2.model_validate({**_hello(), "data_source": "PUBLIC_DATASET_REPLAY"})
    from app.services.sensing_service import resolve_provenance

    class _NoDevice:
        def execute(self, *_a, **_k):
            class R:
                def scalar_one_or_none(self):
                    return None
            return R()

    assert resolve_provenance(_NoDevice(), h) == ("PUBLIC_DATASET_REPLAY", None)
    with pytest.raises(ValueError):
        HelloV2.model_validate({**_hello(simulated=False), "data_source": "PUBLIC_DATASET_REPLAY"})
    with pytest.raises(ValueError):
        HelloV2.model_validate({**_hello(), "force_channels": [{"id": "f", "unit": "N"}]})
    HelloV2.model_validate({**_hello(), "force_channels": [{"id": "f", "unit": "N",
                                                             "calibration_ref": "loadcell-2026-10"}]})


def test_sped_up_stream_is_never_reported_as_clock_drift():
    from app.sensing.stream import StreamMonitor

    m = StreamMonitor(declared_rate_hz=100)
    for k in range(600):                      # 60 s of device time sent in 20 s (3x replay)
        ts = np.arange(k * 10, k * 10 + 10) / 100.0
        m.observe(ts, np.arange(k * 10, k * 10 + 10), np.ones((10, 12)), arrival=1000 + ts[-1] / 3)
    c = m.clock()
    assert c["sync_status"] == "NOT_REAL_TIME" and c["drift_ppm"] is None
    assert c["device_vs_server_rate_ppm"] < -600000


def test_training_export_is_read_by_the_ml_loader(client, clinician, patient_record, tmp_path,
                                                  monkeypatch):
    """backend export -> ml/scripts/finetune_rehabsense.load_export: one format."""
    import importlib.util
    import sys

    pid, headers = patient_record["id"], clinician["headers"]
    sid = _research(client, headers, pid, "P11")
    _record_physical(client, headers, sid, DualImuModel(seed=8), 13.0, "esp32-train-01")
    client.post(f"/api/sessions/{sid}/labels", headers=headers,
                json={"t_start": 10.0, "t_end": 12.0, "activity": "standing"})
    from scripts import export_training_dataset

    out = tmp_path / "train"
    monkeypatch.setattr(sys, "argv", ["x", "--out", str(out)])
    export_training_dataset.main()
    top = json.loads((out / "manifest.json").read_text())
    assert top["provenance_included"] == ["PHYSICAL_REGISTERED"]
    assert any(r["subject"] == "P11" for r in top["recordings"])
    assert top["skipped"].get("SIMULATED", 0) >= 0      # simulated never exported

    ml = Path(__file__).resolve().parents[2] / "ml" / "scripts" / "finetune_rehabsense.py"
    spec = importlib.util.spec_from_file_location("finetune", ml)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _, sessions = mod.load_export(out)
    mine = [s for s in sessions if s["meta"]["subject"] == "P11"]
    assert mine and mine[0]["labels"]["label_activity"].tolist() == ["standing"]
    rep = mod.dataset_report(mine)
    assert rep["subject_count"] == 1 and rep["class_distribution_seconds"] == {"standing": 2.0}
    assert 0 < rep["label_coverage"] < 1
    # The loader rebuilds calibrated windows through the server's own code path.
    t, L, R, gl, gr = mod.calibrated_imu(mine[0])
    assert L.shape[1] == 6 and abs(np.linalg.norm(gl) - 1) < 1e-6


def test_physical_report_refuses_non_physical_and_cites_evidence(client, clinician, patient_record):
    from app.db.database import SessionLocal
    from app.sensing.physical_report import build, to_markdown

    pid, headers = patient_record["id"], clinician["headers"]
    sim = client.post("/api/sessions", headers=headers,
                      json={"patient_id": pid, "exercise_type": "SQUAT"}).json()["id"]
    with client.websocket_connect(f"/ws/ingest/v2/{sim}") as dev:
        dev.send_json(_hello())                       # simulated
        dev.receive_json()
        _stream(dev, DualImuModel(seed=1), 3.0)
    client.post(f"/api/sessions/{sim}/end", headers=headers, json={})
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="PHYSICAL_REGISTERED"):
            build(db, sim)
    finally:
        db.close()

    # A registered, authenticated device (test fixture data, not a real board).
    sid = _research(client, headers, pid, "P12")
    _record_physical(client, headers, sid, DualImuModel(seed=2), 14.0, "esp32-report-01")
    db = SessionLocal()
    try:
        r = build(db, sid, {"frontend.left_status_visible": {"result": "PASS", "evidence": "shot.png"}})
    finally:
        db.close()
    res = r["results"]
    assert res["authentication"]["status"] == "PASS"
    # The test hello declares no WHO_AM_I evidence -> the sensor items cannot PASS.
    assert res["left_sensor"]["status"] == "FAIL" and "WHO_AM_I None" in res["left_sensor"]["evidence"]
    assert res["frontend"]["status"] == "NOT TESTED"        # partial observations only
    assert r["operator_observations"]["device.i2c_scan_0x68_0x69"]["status"] == "NOT TESTED"
    md = to_markdown(r)
    assert "NOT TESTED" in md and r["recording_id"] in md
