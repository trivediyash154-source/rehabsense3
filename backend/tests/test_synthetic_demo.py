"""The synthetic demonstration cohort: provenance, generation, isolation, analytics, PDF.

The seed is run for one cohort member (P04, eight sessions) on the test
database, through the same in-process socket and end endpoint it uses in
production.
"""

from __future__ import annotations

import re
import uuid
import zlib

import numpy as np
import pytest

from app.hardware.protocol_v2 import HelloV2
from app.sensing import provenance as prov
from app.simulator.dual_imu import DualImuModel, SideConfig


def _hello(**extra):
    return {"type": "hello", "protocol_version": 2, "device_id": "t-dev", "sample_rate_hz": 100,
            "imus": [{"side": "LEFT"}, {"side": "RIGHT"}], **extra}


# --------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------- #

def test_synthetic_demonstration_is_a_declared_non_physical_provenance():
    from app.services.sensing_service import resolve_provenance

    class _NoDevice:
        def execute(self, *_a, **_k):
            class R:
                def scalar_one_or_none(self):
                    return None
            return R()

    hello = HelloV2.model_validate(_hello(simulated=True, data_source="SYNTHETIC_DEMONSTRATION"))
    assert resolve_provenance(_NoDevice(), hello) == (prov.SYNTHETIC_DEMONSTRATION, None)
    assert prov.is_non_physical(prov.SYNTHETIC_DEMONSTRATION)
    assert not prov.counts_as_physical_evidence(prov.SYNTHETIC_DEMONSTRATION)
    assert prov.session_mode_for(prov.SYNTHETIC_DEMONSTRATION) == "SIMULATED"
    assert "not clinical evidence" in prov.DESCRIPTION[prov.SYNTHETIC_DEMONSTRATION]
    # A device that does not declare itself simulated can never claim it.
    with pytest.raises(ValueError):
        HelloV2.model_validate(_hello(simulated=False, data_source="SYNTHETIC_DEMONSTRATION"))


# --------------------------------------------------------------------- #
# generator
# --------------------------------------------------------------------- #

def _tilts(model: DualImuModel, side: str, seconds: float = 30.0) -> np.ndarray:
    return np.array([model.tilt(side, t / 100.0) for t in range(int(seconds * 100))])


def test_realism_inputs_default_to_the_original_model():
    plain = DualImuModel(exercise="SQUAT", seed=3, left=SideConfig(severity=0.4))
    explicit = DualImuModel(exercise="SQUAT", seed=3,
                            left=SideConfig(severity=0.4, variability=0.0, tremor_deg=0.0))
    assert np.array_equal(_tilts(plain, "LEFT"), _tilts(explicit, "LEFT"))
    assert plain._warped(12.3) == 12.3


def test_realism_inputs_are_deterministic_and_smooth():
    cfg = SideConfig(severity=0.5, variability=0.2, tremor_deg=0.6)
    a = _tilts(DualImuModel(exercise="SQUAT", seed=9, left=cfg), "LEFT")
    b = _tilts(DualImuModel(exercise="SQUAT", seed=9, left=cfg), "LEFT")
    assert np.array_equal(a, b)
    # No step anywhere: a jump would be an impossible angular velocity.
    assert np.max(np.abs(np.diff(a))) < 2.0
    # Movement time never runs backwards.
    m = DualImuModel(exercise="WALK", seed=9, left=cfg)
    warped = [m._warped(t / 10) for t in range(600)]
    assert all(y > x for x, y in zip(warped, warped[1:]))


def test_variability_spreads_repetition_ranges():
    def peak_spread(variability: float) -> float:
        m = DualImuModel(exercise="SQUAT", seed=5, left=SideConfig(variability=variability))
        x = _tilts(m, "LEFT", 60)
        peaks = [x[i] for i in range(1, len(x) - 1) if x[i] > x[i - 1] and x[i] >= x[i + 1] and x[i] > 10]
        return float(np.std(peaks) / np.mean(peaks))

    assert peak_spread(0.2) > 3 * peak_spread(0.0)


# --------------------------------------------------------------------- #
# the seed, end to end
# --------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def seeded():
    """P04 (eight sessions) seeded once for this module, visible to a clinician."""
    from fastapi.testclient import TestClient

    from app.main import app
    from scripts import seed_demo_data

    client = TestClient(app)
    email = f"clin-demo-{uuid.uuid4().hex[:8]}@example.com"
    password = "a-very-long-passphrase"
    assert client.post("/api/auth/signup", json={"email": email, "password": password, "name": "Dr Demo",
                                                "role": "PHYSIOTHERAPIST"}).status_code == 201
    tokens = client.post("/api/auth/token", json={"email": email, "password": password}).json()
    args = ["--only", "P04", "--no-public-replay", "--clinician-email", email]
    assert seed_demo_data.main(args) == 0
    return {"client": client, "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
            "email": email, "args": args, "module": seed_demo_data}


def _demo_patient(db):
    from sqlalchemy import select

    from app.db.models.patient import PatientProfile

    return db.execute(select(PatientProfile).where(
        PatientProfile.demo_key == "synthetic-demo/v1/P04")).scalar_one_or_none()


def test_seed_streams_every_session_through_the_pipeline(seeded, db):
    from sqlalchemy import func, select

    from app.db.models.report import Report
    from app.db.models.sensing import ActivityResult, RepetitionResult, SensorSampleChunk, SessionTrace
    from app.db.models.session import Session as SessionModel, SessionStatus

    patient = _demo_patient(db)
    assert patient is not None
    assert patient.provenance == prov.SYNTHETIC_DEMONSTRATION
    assert patient.name.startswith("Synthetic demo")
    sessions = db.execute(select(SessionModel).where(SessionModel.patient_id == patient.id)).scalars().all()
    assert len(sessions) == 8
    for s in sessions:
        assert s.status is SessionStatus.COMPLETED
        assert s.provenance == prov.SYNTHETIC_DEMONSTRATION      # set at the handshake
        assert s.protocol_version == 2
        assert s.mode.value == "SIMULATED"
        gen = s.generation
        for key in ("synthetic_generator_version", "seed", "source_dataset", "model_version",
                    "generation_timestamp", "inputs"):
            assert key in gen
        assert gen["label"] == "SYNTHETIC DEMONSTRATION DATA — NOT CLINICAL EVIDENCE"
        assert s.summary["protocol_version"] == 2
        assert (s.summary["movement_quality"] or {}).get("mqi") is not None
        assert s.calibration_state.value in ("COMPLETE", "FAILED")
        # Stored the normal way: raw chunks, repetitions and a replay trace.
        assert db.execute(select(func.count(SensorSampleChunk.id)).where(
            SensorSampleChunk.session_id == s.id)).scalar_one() > 0
        assert db.execute(select(func.count(RepetitionResult.id)).where(
            RepetitionResult.session_id == s.id)).scalar_one() > 0
        assert db.execute(select(func.count(ActivityResult.id)).where(
            ActivityResult.session_id == s.id)).scalar_one() > 0
        assert db.get(SessionTrace, s.id) is not None
    # Dated on the synthetic programme, oldest first, all in the past.
    starts = sorted(s.started_at for s in sessions)
    assert (starts[-1] - starts[0]).days >= 10
    report = db.execute(select(Report).where(Report.patient_id == patient.id)).scalar_one()
    assert report.status.value == "READY" and report.kind.value == "MOVEMENT_PROGRESS"


def test_seed_is_idempotent(seeded, db, capsys):
    from sqlalchemy import func, select

    from app.db.models.patient import PatientProfile
    from app.db.models.session import Session as SessionModel

    before = db.execute(select(func.count(SessionModel.id))).scalar_one()
    assert seeded["module"].main(seeded["args"]) == 0
    out = capsys.readouterr().out
    assert "0 sessions generated, 8 already present" in out
    db.expire_all()
    assert db.execute(select(func.count(SessionModel.id))).scalar_one() == before
    assert db.execute(select(func.count(PatientProfile.id)).where(
        PatientProfile.demo_key.is_not(None))).scalar_one() == 1


def test_assignment_never_creates_or_changes_accounts(seeded):
    with pytest.raises(SystemExit):
        seeded["module"].main(["--only", "P04", "--no-public-replay",
                               "--clinician-email", "nobody-here@example.com"])


def test_analytics_endpoints_read_the_stored_cohort(seeded):
    c, h = seeded["client"], seeded["headers"]
    ov = c.get("/api/analytics/overview", headers=h).json()
    assert ov["synthetic"] is True
    assert ov["kpis"]["total_sessions"] == 8 and ov["kpis"]["patients"] == 1
    assert ov["provenance"]["sessions"] == {"SYNTHETIC_DEMONSTRATION": 8}
    assert ov["labels"]["provenance"] == "SYNTHETIC DEMONSTRATION DATA — NOT CLINICAL EVIDENCE"
    roster = c.get("/api/analytics/patients", headers=h).json()
    entry = roster["items"][0]
    assert entry["provenance"] == "SYNTHETIC_DEMONSTRATION"
    assert entry["status"] in ("IMPROVING", "STABLE", "NEEDS_ATTENTION", "COMPLETED")
    detail = c.get(f"/api/analytics/patients/{entry['id']}", headers=h).json()
    assert detail["summary"]["sessions_completed"] == 8
    assert detail["summary"]["initial_mqi"] is not None
    sessions = c.get("/api/analytics/sessions", headers=h).json()["items"]
    assert len(sessions) == 8 and all(s["provenance"] == "SYNTHETIC_DEMONSTRATION" for s in sessions)
    sid = sessions[0]["id"]
    analysis = c.get(f"/api/sessions/{sid}/analysis", headers=h).json()
    assert analysis["generation"]["synthetic_generator_version"] == "synthetic-demo-v1"
    assert analysis["provenance"] == "SYNTHETIC_DEMONSTRATION"
    trace = c.get(f"/api/sessions/{sid}/trace", headers=h).json()
    assert trace["columns"][:4] == ["t", "left_acc_g", "left_gyro_dps", "left_tilt_deg"]
    assert len(trace["rows"]) > 100
    ex = c.get("/api/analytics/exercises", headers=h).json()["items"]
    assert sum(e["sessions"] for e in ex) == 8
    research = c.get("/api/analytics/research", headers=h).json()
    assert research["dataset"]["physical_sessions"] == 0
    assert research["dataset"]["samples"] > 0
    assert research["validation"]["clinical"] == "NOT_VALIDATED"


def _pdf_text(pdf: bytes) -> bytes:
    """Inflate every content stream so the drawn text can be searched."""
    out = b""
    for m in re.finditer(rb"stream\n(.*?)\nendstream", pdf, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            pass
    return out


def test_report_pdf_carries_the_mandatory_disclaimers(seeded):
    c, h = seeded["client"], seeded["headers"]
    items = c.get("/api/reports", headers=h).json()["items"]
    report = next(i for i in items if i["kind"] == "MOVEMENT_PROGRESS")
    assert report["pdf"] is True and report["provenance"] == "SYNTHETIC_DEMONSTRATION"
    r = c.get(f"/api/reports/{report['id']}/pdf", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-1.4") and r.content.rstrip().endswith(b"%%EOF")
    text = _pdf_text(r.content)
    assert "SYNTHETIC DEMONSTRATION DATA — NOT CLINICAL EVIDENCE".encode("cp1252") in text
    assert b"RehabSense is a research prototype and not a medical device." in text
    assert text.count(b"RehabSense is a research prototype and not a medical device.") >= 2  # every page


def test_report_generation_through_the_api(seeded):
    c, h = seeded["client"], seeded["headers"]
    pid = c.get("/api/analytics/patients", headers=h).json()["items"][0]["id"]
    created = c.post("/api/reports", headers=h, json={"patient_id": pid, "kind": "MOVEMENT_PROGRESS"}).json()
    done = c.post(f"/api/reports/{created['id']}/generate", headers=h)
    assert done.status_code == 200 and done.json()["status"] == "READY"
    body = c.get(f"/api/reports/{created['id']}", headers=h).json()
    assert body["payload"]["type"] == "MOVEMENT_PROGRESS"
    assert "SYNTHETIC DEMONSTRATION DATA — NOT CLINICAL EVIDENCE" in body["payload"]["disclaimers"]


def test_the_cohort_is_invisible_to_unassigned_accounts(seeded, client, clinician):
    h = clinician["headers"]
    assert client.get("/api/analytics/overview", headers=h).json()["kpis"]["total_sessions"] == 0
    assert client.get("/api/analytics/sessions", headers=h).json()["items"] == []
    report_id = next(i["id"] for i in seeded["client"].get("/api/reports", headers=seeded["headers"]).json()["items"])
    assert client.get(f"/api/reports/{report_id}/pdf", headers=h).status_code == 404


def test_reset_touches_only_the_demo_namespace(seeded, db):
    from sqlalchemy import func, select

    from app.db.models.patient import Leg, PatientProfile
    from app.db.models.session import Session as SessionModel

    real = PatientProfile(name="Real record kept", operated_leg=Leg.LEFT)
    db.add(real)
    db.commit()
    real_id = real.id
    patient_id = _demo_patient(db).id
    demo_sessions = db.execute(select(func.count(SessionModel.id)).where(
        SessionModel.patient_id == patient_id)).scalar_one()
    assert demo_sessions == 8
    assert seeded["module"].main(["--reset-demo"]) == 0
    db.expire_all()
    assert _demo_patient(db) is None
    assert db.execute(select(func.count(SessionModel.id)).where(
        SessionModel.patient_id == patient_id)).scalar_one() == 0
    assert db.get(PatientProfile, real_id) is not None


def test_reset_refuses_when_a_demo_record_holds_real_data(db):
    from datetime import datetime, timezone

    from app.db.models.patient import Leg, PatientProfile
    from app.db.models.session import ExerciseType, Session as SessionModel, SessionStatus
    from scripts import seed_demo_data

    p = PatientProfile(name="Synthetic demo · trap", operated_leg=Leg.LEFT,
                       provenance=prov.SYNTHETIC_DEMONSTRATION, demo_key="synthetic-demo/v1/TRAP")
    db.add(p)
    db.flush()
    db.add(SessionModel(patient_id=p.id, exercise_type=ExerciseType.SQUAT, status=SessionStatus.COMPLETED,
                        started_at=datetime.now(timezone.utc), provenance=prov.PHYSICAL_REGISTERED))
    db.commit()
    with pytest.raises(SystemExit) as refused:
        seed_demo_data.main(["--reset-demo"])
    assert "not generated data" in str(refused.value)
    db.expire_all()
    assert db.get(PatientProfile, p.id) is not None
    db.delete(p)
    db.commit()


def test_concurrent_first_registration_of_a_device_id_does_not_fail(db):
    """Two streams announcing one new device id at once: the loser of the
    unique-key race reuses the winner's row instead of failing its handshake."""
    from sqlalchemy import select

    from app.db.database import SessionLocal
    from app.db.models.device import Device
    from app.services import sensing_service

    device_id = f"race-{uuid.uuid4().hex[:8]}"
    other = SessionLocal()
    real_execute = db.execute
    calls = {"n": 0}

    def racing_execute(statement, *args, **kwargs):
        # The first lookup misses; meanwhile another connection inserts it.
        result = real_execute(statement, *args, **kwargs)
        if calls["n"] == 0 and "devices" in str(statement):
            calls["n"] += 1
            other.add(Device(device_id=device_id))
            other.commit()

            class Miss:
                def scalar_one_or_none(self):
                    return None
            return Miss()
        return result

    db.execute = racing_execute
    try:
        row = sensing_service._device_row(db, device_id)
    finally:
        db.execute = real_execute
        other.close()
    assert row.device_id == device_id
    assert db.execute(select(Device).where(Device.device_id == device_id)).scalars().all() == [row]
