"""Synthetic demonstration cohort, generated through the real RehabSense pipeline.

    SYNTHETIC DEMONSTRATION DATA -- NOT CLINICAL VALIDATION.

    python -m scripts.seed_demo_data --plan                    # print the schedule, write nothing
    python -m scripts.seed_demo_data --clinician-email you@example.org
    python -m scripts.seed_demo_data --reset-demo              # remove the demo namespace only
    python -m scripts.seed_demo_data --reset-demo --regenerate --clinician-email you@example.org

Run from backend/ with DATABASE_URL pointing at the target database. A
database that is not local also needs --yes.

What it creates, and how
------------------------
Five fictional patients (names marked "Synthetic demo"), each with a designed
recovery trajectory, plus one public-dataset reference record. Every session
is produced the way a device session is:

    generator (app/simulator/dual_imu.py, or a replayed public recording)
      -> /ws/ingest/v2/{session}      the socket the ESP32 firmware uses
      -> handshake, provenance, stream checks, calibration, windowing,
         activity model, bilateral asymmetry, repetitions, MQI, persistence
      -> POST /api/sessions/{id}/end  the endpoint a clinician's "End" calls
      -> report_service               the same report builder the UI calls

Nothing downstream of the generator is computed here. The trajectory lives in
the generator *inputs* (severity, rep-to-rep variability, tremor, packet loss,
session length), recorded on every session in `sessions.generation`; the
numbers on screen are whatever the unchanged pipeline measured from those
signals.

Isolation
---------
* Patients carry provenance SYNTHETIC_DEMONSTRATION or PUBLIC_DATASET_REPLAY
  and a demo_key under NAMESPACE; sessions carry idempotency keys under it.
  Running twice skips everything already generated.
* --reset-demo deletes only patients in this namespace, and refuses if any
  of their sessions is anything but generated/replayed data.
* Real accounts are never created or modified. --clinician-email only adds an
  assignment to the demo records so that an existing clinician can see them.
  The generated rows are written by a separate generator account that has no
  password and no sign-in identity, so nobody can sign in as it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import logging
import math
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# Configure before any app module reads settings. The cross-instance live relay
# is never wanted from a script: nothing watches these sessions live.
os.environ["LIVE_RELAY"] = "off"
os.environ.setdefault("ML_MODEL_DIR", str(REPO / "ml" / "artifacts"))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402

GENERATOR = "rehabsense-synthetic-demo"
GENERATOR_VERSION = "synthetic-demo-v1"
NAMESPACE = "synthetic-demo/v1"
DEFAULT_SEED = 20261007
DEMO_DEVICE_ID = "DEMO-ESP32-001"
REPLAY_DEVICE_ID = "DEMO-REPLAY-DSADS"
GENERATOR_EMAIL = "synthetic-demo-generator@example.com"
GENERATOR_NAME = "Synthetic demo generator (not a person)"
RATE_HZ = 100.0
BATCH = 10
LABEL_SYNTHETIC = "SYNTHETIC DEMONSTRATION DATA — NOT CLINICAL EVIDENCE"
LABEL_REPLAY = "PUBLIC DATASET REPLAY — NOT REHABSENSE HARDWARE DATA"
SYNTHETIC_SOURCE = ("none — parametric kinematic model (app/simulator/dual_imu.py); "
                    "no recorded human movement")
DSADS_SOURCE = ("UCI Daily and Sports Activities (Barshan & Altun), CC BY 4.0 — "
                "leg units of one public subject, re-expressed as protocol-v2 samples")
IST = timezone(timedelta(hours=5, minutes=30))


# --------------------------------------------------------------------- #
# the cohort
# --------------------------------------------------------------------- #

@dataclass(frozen=True)
class Member:
    key: str
    name: str
    preferred_name: str
    age: int
    operated_leg: str
    program: str
    program_days: int
    planned_sessions: int
    sessions: int
    trajectory: str
    exercises: tuple[str, ...]
    # Last programme day, counted back from today (0 = today).
    ends_days_ago: int


COHORT: tuple[Member, ...] = (
    Member("P01", "Synthetic demo · Aarav", "Aarav", 34, "LEFT", "Lower-limb rehabilitation",
           60, 24, 21, "STRONG_IMPROVEMENT", ("SQUAT", "SIT_TO_STAND", "STEP_UP", "WALK"), 0),
    Member("P02", "Synthetic demo · Riya", "Riya", 29, "RIGHT", "Bilateral movement rehabilitation",
           30, 15, 13, "MODERATE_IMPROVEMENT", ("SQUAT", "SIT_TO_STAND"), 0),
    Member("P03", "Synthetic demo · Kabir", "Kabir", 52, "LEFT", "Mobility and gait",
           20, 10, 9, "STABLE", ("WALK", "WALK", "STEP_UP"), 0),
    Member("P04", "Synthetic demo · Ananya", "Ananya", 41, "RIGHT", "Lower-limb rehabilitation",
           15, 8, 8, "RAPID_THEN_PLATEAU", ("SIT_TO_STAND", "SQUAT", "KNEE_EXTENSION"), 4),
    Member("P05", "Synthetic demo · Dev", "Dev", 46, "LEFT", "Movement symmetry",
           20, 12, 10, "MIXED_DECLINING", ("SQUAT", "WALK", "STEP_UP"), 0),
)

TRAJECTORY_TEXT = {
    "STRONG_IMPROVEMENT": "60 days: marked asymmetry and variability at the start, steadily closing.",
    "MODERATE_IMPROVEMENT": "30 days: small change to day 10, clear improvement to day 20, then holding.",
    "STABLE": "20 days: natural session-to-session fluctuation around a steady level.",
    "RAPID_THEN_PLATEAU": "15 days: fast improvement over the first week, then a plateau.",
    "MIXED_DECLINING": "20 days: early improvement, then deterioration with rising variability.",
}

# Public-dataset reference record: one replayed recording per subject.
DSADS_KEY = "DSADS"
DSADS_NAME = "Public dataset reference · UCI DSADS"
# (activity code, dataset segment). Standing first: the device calibration
# needs a still period, exactly as a person following the LED would give it.
DSADS_PLAN = (("a02", 2), ("a02", 3), ("a09", 21), ("a09", 22), ("a09", 23), ("a05", 21),
              ("a05", 22), ("a06", 21), ("a06", 22), ("a15", 21), ("a15", 22), ("a01", 21),
              ("a01", 22))


def clip(x: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, x)))


def derived_seed(*parts) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:4], "big")


def impairment(trajectory: str, day: int, rng: np.random.Generator) -> float:
    """Latent impairment in [0, 1] on programme day `day` (1 = first day).

    This is the designed trajectory. It only ever sets generator inputs; the
    measured metrics come from the pipeline.
    """
    if trajectory == "STRONG_IMPROVEMENT":
        base, sd = 0.14 + 0.68 * math.exp(-(day - 1) / 20.0), 0.035
    elif trajectory == "MODERATE_IMPROVEMENT":
        if day <= 10:
            base = 0.62 - 0.05 * (day - 1) / 9.0
        elif day <= 20:
            base = 0.57 - 0.19 * (day - 10) / 10.0
        else:
            base = 0.38 - 0.06 * (day - 20) / 10.0
        sd = 0.035
    elif trajectory == "STABLE":
        base, sd = 0.37 + 0.025 * math.sin(day / 2.7), 0.045
    elif trajectory == "RAPID_THEN_PLATEAU":
        base = 0.78 - 0.42 * min(1.0, (day - 1) / 6.0) if day <= 7 else 0.355
        sd = 0.03
    elif trajectory == "MIXED_DECLINING":
        base = 0.52 - 0.17 * (day - 1) / 7.0 if day <= 8 else 0.35 + 0.30 * (day - 8) / 12.0
        sd = 0.045
    else:  # pragma: no cover - definitions above are exhaustive
        raise ValueError(trajectory)
    return clip(base + rng.normal(0.0, sd), 0.03, 0.95)


def generator_inputs(member: Member, day: int, level: float, rng: np.random.Generator) -> dict:
    """Map the latent level onto the motion model's physical inputs."""
    declining = member.trajectory == "MIXED_DECLINING" and day > 8
    extra_var = 0.06 * (day - 8) / 12.0 if declining else 0.0
    affected = {
        "severity": round(clip(0.03 + 0.85 * level, 0.0, 0.85), 4),
        "variability": round(clip(0.02 + 0.20 * level + extra_var + rng.normal(0, 0.008), 0.0, 0.3), 4),
        "tremor_deg": round(clip(0.05 + 0.80 * level + rng.normal(0, 0.04), 0.0, 1.0), 3),
        "delay_s": round(0.12 * level, 3),
        "noise_scale": round(1.0 + 0.5 * level * rng.uniform(0.5, 1.5), 3),
    }
    unaffected = {
        "severity": round(clip(0.02 + 0.08 * level + rng.normal(0, 0.012), 0.0, 0.2), 4),
        "variability": round(affected["variability"] * 0.55, 4),
        "tremor_deg": round(affected["tremor_deg"] * 0.35, 3),
        "delay_s": 0.0,
        "noise_scale": round(1.0 + 0.2 * level * rng.uniform(0.5, 1.5), 3),
    }
    left, right = (affected, unaffected) if member.operated_leg == "LEFT" else (unaffected, affected)
    return {
        "left": left,
        "right": right,
        "packet_loss": round(clip(0.002 + 0.025 * level * rng.uniform(0.4, 1.6), 0.0, 0.05), 4),
        "movement_s": round(clip(32 + 34 * (1 - level) + rng.normal(0, 4), 25, 75), 1),
        "reported_pain": int(clip(round(0.8 + 7.5 * level + rng.normal(0, 0.7)), 0, 10)),
    }


@dataclass
class PlannedSession:
    member: Member
    index: int
    day: int
    started_at: datetime
    exercise: str
    level: float
    inputs: dict
    seed: int
    key: str = field(init=False)

    def __post_init__(self) -> None:
        self.key = f"{NAMESPACE}/{self.member.key}/S{self.index:02d}"


def session_days(member: Member, rng: np.random.Generator) -> list[int]:
    """Distinct programme days, first and last included, roughly evenly spread."""
    n, d = member.sessions, member.program_days
    days = {1, d}
    for k in range(1, n - 1):
        target = 1 + round(k * (d - 1) / (n - 1)) + int(rng.integers(-1, 2))
        days.add(int(clip(target, 2, d - 1)))
    # Collisions from the jitter are resolved by filling the nearest free day.
    free = [x for x in range(2, d) if x not in days]
    while len(days) < n and free:
        days.add(free.pop(int(rng.integers(0, len(free)))))
    return sorted(days)[:n]


def plan(seed: int, today: date | None = None, now: datetime | None = None) -> list[PlannedSession]:
    now = now or datetime.now(timezone.utc)
    today = today or now.astimezone(IST).date()
    out: list[PlannedSession] = []
    for member in COHORT:
        rng = np.random.default_rng(derived_seed(seed, member.key, "schedule"))
        start = today - timedelta(days=member.program_days - 1 + member.ends_days_ago)
        for index, day in enumerate(session_days(member, rng), start=1):
            level = impairment(member.trajectory, day, rng)
            inputs = generator_inputs(member, day, level, rng)
            minutes = int(rng.integers(7 * 60 + 30, 19 * 60))
            local = datetime.combine(start + timedelta(days=day - 1), datetime.min.time(), IST) \
                + timedelta(minutes=minutes)
            started = local.astimezone(timezone.utc)
            if started > now - timedelta(minutes=20):
                # Never in the future: today's session happened earlier today.
                started = now - timedelta(minutes=int(rng.integers(40, 180)))
            # Mostly the programme's rotation, occasionally a different one.
            rotation = member.exercises
            exercise = rotation[(index - 1) % len(rotation)]
            if rng.random() < 0.15:
                exercise = rotation[int(rng.integers(0, len(rotation)))]
            out.append(PlannedSession(member=member, index=index, day=day, started_at=started,
                                      exercise=exercise, level=level, inputs=inputs,
                                      seed=derived_seed(seed, member.key, index)))
    return out


# --------------------------------------------------------------------- #
# database helpers
# --------------------------------------------------------------------- #

def _redacted(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
        host = parts.hostname or parts.path or "?"
        return f"{parts.scheme}://{host}/{(parts.path or '').lstrip('/').split('?')[0]}"
    except Exception:  # pragma: no cover - display only
        return "<unparseable>"


def _is_local(url: str) -> bool:
    from urllib.parse import parse_qs, urlsplit

    if url.startswith("sqlite"):
        return True
    parts = urlsplit(url)
    host = parts.hostname or ""
    socket_dir = parse_qs(parts.query).get("host", [""])[0]
    return host in ("localhost", "127.0.0.1", "::1") or (not host and socket_dir.startswith("/"))


def generator_account(db):
    """The account generated rows are written by. No password, no identity."""
    from sqlalchemy import select

    from app.db.models.user import Role, User

    user = db.execute(select(User).where(User.email == GENERATOR_EMAIL)).scalar_one_or_none()
    if user is None:
        user = User(email=GENERATOR_EMAIL, name=GENERATOR_NAME, role=Role.PHYSIOTHERAPIST,
                    password_hash=None, is_active=True,
                    preferences={"synthetic_demo_generator": True})
        db.add(user)
        db.flush()
    return user


def visible_to(db, clinician_emails: list[str]) -> list:
    """Existing clinician accounts the cohort should be visible to. Never creates."""
    from sqlalchemy import func, select

    from app.db.models.user import Role, User

    users = []
    for email in clinician_emails:
        user = db.execute(select(User).where(func.lower(User.email) == email.strip().lower())
                          ).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"--clinician-email {email}: no such account. Sign in once first; "
                             "this script never creates or changes real accounts.")
        if user.role not in (Role.PHYSIOTHERAPIST, Role.ADMIN):
            raise SystemExit(f"--clinician-email {email}: role {user.role.value} cannot hold "
                             "patient assignments (needs a clinician or admin account).")
        users.append(user)
    return users


def ensure_assignment(db, patient_id: int, clinician_id: int) -> bool:
    from sqlalchemy import select

    from app.db.models.patient import AssignmentStatus, PatientAssignment

    row = db.execute(select(PatientAssignment).where(
        PatientAssignment.patient_id == patient_id,
        PatientAssignment.clinician_id == clinician_id)).scalar_one_or_none()
    if row is None:
        db.add(PatientAssignment(patient_id=patient_id, clinician_id=clinician_id,
                                 status=AssignmentStatus.ACTIVE,
                                 assigned_at=datetime.now(timezone.utc)))
        return True
    if row.status is not AssignmentStatus.ACTIVE:
        row.status = AssignmentStatus.ACTIVE
        row.ended_at = None
        return True
    return False


def ensure_patient(db, *, key: str, name: str, preferred_name: str | None, age: int | None,
                   operated_leg: str, provenance: str, program: str, program_days: int | None,
                   planned_sessions: int | None, recovery_start: date | None, notes: str,
                   actor) -> tuple[object, bool]:
    from sqlalchemy import select

    from app.db.models.audit import AuditAction
    from app.db.models.patient import Leg, PatientProfile
    from app.services import audit_service

    demo_key = f"{NAMESPACE}/{key}"
    patient = db.execute(select(PatientProfile).where(PatientProfile.demo_key == demo_key)
                         ).scalar_one_or_none()
    created = patient is None
    if created:
        patient = PatientProfile(demo_key=demo_key, operated_leg=Leg(operated_leg), name=name)
        db.add(patient)
    patient.name = name
    patient.preferred_name = preferred_name
    patient.age = age
    patient.operated_leg = Leg(operated_leg)
    patient.provenance = provenance
    patient.program = program
    patient.program_days = program_days
    patient.planned_sessions = planned_sessions
    patient.recovery_start = recovery_start
    patient.notes = notes
    db.flush()
    if created:
        audit_service.record(db, action=AuditAction.PATIENT_CREATED, entity_type="patient",
                             entity_id=patient.id, actor_id=actor.id, provenance=provenance,
                             demo_key=demo_key)
    return patient, created


# --------------------------------------------------------------------- #
# streaming through the real ingestion socket
# --------------------------------------------------------------------- #

class _DisconnectWatch(logging.Handler):
    """Signals when the ingest handler has finished a session's disconnect.

    The in-process test client cancels the server's socket task as soon as
    its context exits. The script therefore closes the socket itself and
    waits for the handler's own "hw_device_detached" event (logged after the
    final raw chunk is stored and the device is marked offline), exactly the
    point a real device's socket closure reaches on its own.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self._done: set[int] = set()
        self._cv = threading.Condition()

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() != "hw_device_detached":
            return
        session_id = (getattr(record, "context", None) or {}).get("session_id")
        with self._cv:
            self._done.add(session_id)
            self._cv.notify_all()

    def wait(self, session_id: int, timeout: float = 120.0) -> None:
        with self._cv:
            if not self._cv.wait_for(lambda: session_id in self._done, timeout):
                raise RuntimeError(f"session {session_id}: the ingest handler did not finish the disconnect")


_DETACHED = _DisconnectWatch()
logging.getLogger("rehabsense.ingest").addHandler(_DETACHED)

def hello_frame(*, device_id: str, firmware: str, data_source: str, scenario: str,
                force: bool, placement: str = "SHANK") -> dict:
    """The protocol-v2 hello, as the firmware builds it -- declared simulated."""
    imus = [{"side": side, "placement": placement, "model": "MPU6050", "i2c_address": addr,
             "accel_range_g": 4, "gyro_range_dps": 500}
            for side, addr in (("LEFT", "0x68"), ("RIGHT", "0x69"))]
    from app.core.config import get_settings

    hello = {
        "type": "hello", "protocol_version": 2, "device_id": device_id,
        "firmware_version": firmware, "sample_rate_hz": RATE_HZ, "imus": imus,
        "force_channels": [{"id": fid, "side": side, "location": "HEEL", "sensor": "FSR402",
                            "unit": "adc_norm"}
                           for fid, side in (("heel_left", "LEFT"), ("heel_right", "RIGHT"))] if force else [],
        # Declared, never inferred: this is what makes the session non-physical.
        "simulated": True,
        "data_source": data_source,
        "scenario": scenario,
    }
    key = get_settings().device_ingest_key
    if key:
        hello["device_key"] = key
    return hello


def _send_samples(ws, session_id: int, samples: list[dict], rng: np.random.Generator,
                  packet_loss: float) -> dict:
    sent = dropped = 0
    for k in range(0, len(samples), BATCH):
        batch = samples[k:k + BATCH]
        if packet_loss and rng.random() < packet_loss:
            dropped += 1          # a Wi-Fi packet that never arrived
        else:
            ws.send_json({"type": "data", "samples": batch, "sent_ts": batch[-1]["ts"]})
            sent += 1
        if (k // BATCH) % 100 == 0:
            ws.send_json({"type": "status", "battery_pct": round(92.0 - 0.02 * (k / BATCH), 1),
                          "wifi_rssi_dbm": round(float(-55 - 8 * rng.random()), 1),
                          "imu_left_ok": True, "imu_right_ok": True})
    # Packets are processed in order: a pong means every sample above landed.
    ws.send_json({"type": "ping"})
    while ws.receive_json().get("type") != "pong":
        pass
    # The device stops streaming: close, and let the server finish the
    # disconnect (final raw chunk, device offline) before moving on.
    ws.close(1000)
    _DETACHED.wait(session_id)
    return {"packets_sent": sent, "packets_dropped": dropped, "samples_generated": len(samples)}


def stream_synthetic(client, session_id: int, p: PlannedSession) -> dict:
    from app.simulator.dual_imu import DualImuModel, SideConfig

    with client.websocket_connect(f"/ws/ingest/v2/{session_id}") as ws:
        ws.send_json(hello_frame(device_id=DEMO_DEVICE_ID, firmware="synthetic-demo-1.0",
                                 data_source="SYNTHETIC_DEMONSTRATION", scenario="SYNTHETIC_DEMO",
                                 force=True))
        ack = ws.receive_json()
        if ack.get("type") != "hello_ack":
            raise RuntimeError(f"handshake refused: {ack}")
        still = ack.get("calibration_health_seconds", 1.0) + ack["calibration_still_seconds"] + 1.0
        move = ack["calibration_movement_seconds"]
        model = DualImuModel(exercise=p.exercise, rate_hz=RATE_HZ, seed=p.seed,
                             left=SideConfig(**p.inputs["left"]), right=SideConfig(**p.inputs["right"]),
                             still_s=still, calib_move_s=move)
        n = int((still + move + p.inputs["movement_s"]) * RATE_HZ)
        samples = [{"ts": round(i / RATE_HZ, 4), "seq": i, **model.sample(i / RATE_HZ)} for i in range(n)]
        rng = np.random.default_rng(derived_seed(p.seed, "packets"))
        return _send_samples(ws, session_id, samples, rng, p.inputs["packet_loss"])


def _dsads_tools():
    """The public replay helpers that already exist in ml/ (one implementation)."""
    ml_dir = REPO / "ml"
    if str(ml_dir) not in sys.path:
        sys.path.insert(0, str(ml_dir))
    from rehabsense_ml.datasets import daily_sports

    spec = importlib.util.spec_from_file_location(
        "_replay_through_device_pipeline", ml_dir / "scripts" / "replay_through_device_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return daily_sports, module.to_device


def dsads_available() -> bool:
    return (REPO / "ml" / "data" / "cache" / "daily_sports.npz").exists() or \
        (REPO / "ml" / "data" / "raw" / "daily_sports").exists()


def stream_dsads(client, session_id: int, subject: str, by_key: dict, to_device, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    samples: list[dict] = []
    segments: list[dict] = []
    t, seq = 0.0, 0
    for code, seg in DSADS_PLAN:
        rec = by_key[(subject, code, seg)]
        ts, dev = to_device(np.column_stack([rec.left, rec.right]), t, rng)
        segments.append({"activity_code": code, "label": rec.label, "dataset_segment": seg,
                         "t_start": round(float(ts[0]), 3), "t_end": round(float(ts[-1]), 3)})
        for i in range(len(ts)):
            samples.append({"ts": round(float(ts[i]), 5), "seq": seq,
                            "imu_left": dict(zip(("ax", "ay", "az", "gx", "gy", "gz"),
                                                 (round(float(x), 5) for x in dev[i, 0:6]))),
                            "imu_right": dict(zip(("ax", "ay", "az", "gx", "gy", "gz"),
                                                  (round(float(x), 5) for x in dev[i, 6:12])))})
            seq += 1
        t = float(ts[-1]) + 0.01
    with client.websocket_connect(f"/ws/ingest/v2/{session_id}") as ws:
        ws.send_json(hello_frame(device_id=REPLAY_DEVICE_ID, firmware="dataset-replay-1.0",
                                 data_source="PUBLIC_DATASET_REPLAY", scenario="DSADS_REPLAY",
                                 force=False))
        ack = ws.receive_json()
        if ack.get("type") != "hello_ack":
            raise RuntimeError(f"handshake refused: {ack}")
        stats = _send_samples(ws, session_id, samples, rng, 0.0)
    return {**stats, "segments": segments}


# --------------------------------------------------------------------- #
# after the pipeline: end, then date the session on its synthetic timeline
# --------------------------------------------------------------------- #

def end_through_api(client, token: str, session_id: int, pain: int | None, notes: str) -> dict:
    body = {"notes": notes}
    if pain is not None:
        body["reported_pain"] = pain
    r = client.post(f"/api/sessions/{session_id}/end", json=body,
                    headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise RuntimeError(f"ending session {session_id} failed: {r.status_code} {r.text[:300]}")
    return r.json()


def backdate(db, session_id: int, target_start: datetime) -> None:
    """Place a finished session on its synthetic programme day.

    Only timestamps move, all by the same offset; every measured value stays
    exactly as the pipeline stored it. Audit entries keep their real time:
    they record when generation actually happened. Raw-sample expiry is left
    alone, so retention still counts from when the samples were stored.
    """
    from sqlalchemy import select, update

    from app.db.models.sensing import (
        DeviceCalibration,
        Recording,
        SensorSampleChunk,
        SessionMarker,
        SessionTrace,
    )
    from app.db.models.session import Session as SessionModel
    from app.services import sensing_service

    from app.db.models.base import as_utc

    session = db.get(SessionModel, session_id)
    shift = target_start - as_utc(session.started_at)
    session.started_at = as_utc(session.started_at) + shift
    if session.ended_at is not None:
        session.ended_at = as_utc(session.ended_at) + shift
    session.created_at = as_utc(session.created_at) + shift
    postgres = db.get_bind().dialect.name == "postgresql"
    for model, cols in ((Recording, ("started_at", "ended_at", "created_at", "updated_at")),
                        (DeviceCalibration, ("created_at", "updated_at")),
                        (SensorSampleChunk, ("created_at",)),
                        (SessionMarker, ("server_ts",)),
                        (SessionTrace, ("created_at",))):
        if postgres:
            # One statement per table (timestamp + interval) instead of a
            # round trip per row to a remote database.
            db.execute(update(model).where(model.session_id == session_id)
                       .values(**{c: getattr(model, c) + shift for c in cols}))
            continue
        for row in db.execute(select(model).where(model.session_id == session_id)).scalars():
            for c in cols:
                value = getattr(row, c)
                if value is not None:
                    setattr(row, c, as_utc(value) + shift)
    db.flush()
    # The recording's metadata quotes its start/end: rebuild it from the
    # moved rows through the normal path, rather than editing the JSON.
    sensing_service.finalize_recording(db, session_id)
    db.flush()


# --------------------------------------------------------------------- #
# reset
# --------------------------------------------------------------------- #

def reset_demo(db, actor_email: str = GENERATOR_EMAIL) -> dict:
    """Delete the demo namespace. Refuses rather than delete anything else."""
    from sqlalchemy import delete, func, select

    from app.db.models.audit import AuditAction
    from app.db.models.device import Device
    from app.db.models.patient import PatientProfile
    from app.db.models.sensing import Recording
    from app.db.models.session import Session as SessionModel
    from app.db.models.user import User
    from app.sensing import provenance as prov
    from app.services import audit_service

    patients = db.execute(select(PatientProfile).where(
        PatientProfile.demo_key.like(f"{NAMESPACE}/%"))).scalars().all()
    for patient in patients:
        if patient.provenance not in (prov.SYNTHETIC_DEMONSTRATION, prov.PUBLIC_DATASET_REPLAY):
            raise SystemExit(f"refusing to reset: patient {patient.id} is in the demo namespace "
                             f"but has provenance {patient.provenance!r}")
    ids = [p.id for p in patients]
    if ids:
        foreign = db.execute(select(func.count(SessionModel.id)).where(
            SessionModel.patient_id.in_(ids),
            (SessionModel.provenance.is_(None)) | (SessionModel.provenance.not_in(prov.NON_PHYSICAL)),
            SessionModel.status == "COMPLETED")).scalar_one()
        if foreign:
            raise SystemExit(f"refusing to reset: {foreign} completed session(s) under the demo "
                             "records are not generated data. Nothing was deleted.")
    sessions = 0
    if ids:
        sessions = db.execute(select(func.count(SessionModel.id)).where(
            SessionModel.patient_id.in_(ids))).scalar_one()
        # The database cascades to sessions, samples, results, reports and
        # assignments; nothing outside these patient rows is addressed.
        db.execute(delete(PatientProfile).where(PatientProfile.id.in_(ids),
                                                PatientProfile.demo_key.like(f"{NAMESPACE}/%")))
    devices = 0
    db.flush()
    for device_id in (DEMO_DEVICE_ID, REPLAY_DEVICE_ID):
        device = db.execute(select(Device).where(Device.device_id == device_id)).scalar_one_or_none()
        if device is None or device.key_hash is not None:
            continue   # absent, or a registered (keyed) device: never ours to delete
        # Still referenced by a recording outside the namespace? Then keep it.
        still_used = db.execute(select(func.count(Recording.id)).where(
            Recording.device_pk == device.id)).scalar_one()
        if not still_used:
            db.delete(device)
            devices += 1
    actor = db.execute(select(User).where(User.email == actor_email)).scalar_one_or_none()
    audit_service.record(db, action=AuditAction.DEMO_DATA_RESET, entity_type="demo_namespace",
                         entity_id=NAMESPACE, actor_id=actor.id if actor else None,
                         patients=len(ids), sessions=sessions, devices=devices)
    db.commit()
    return {"patients": len(ids), "sessions": sessions, "devices": devices}


# --------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------- #

def _session_notes(p: PlannedSession) -> str:
    m = p.member
    return (f"{LABEL_SYNTHETIC}. Generated session {p.index} of {m.sessions}, programme day "
            f"{p.day} of {m.program_days} ({m.program}). Trajectory: {TRAJECTORY_TEXT[m.trajectory]} "
            "Not recorded from a person.")


def _generation(p: PlannedSession, seed: int, model_ref: str | None) -> dict:
    from app.sensing.processor import PIPELINE_VERSION

    return {
        "provenance": "SYNTHETIC_DEMONSTRATION",
        "label": LABEL_SYNTHETIC,
        "generator": GENERATOR,
        "synthetic_generator_version": GENERATOR_VERSION,
        "seed": seed,
        "session_seed": p.seed,
        "source_dataset": SYNTHETIC_SOURCE,
        "model_version": model_ref,
        "pipeline_version": PIPELINE_VERSION,
        "generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "cohort_key": p.member.key,
        "trajectory": p.member.trajectory,
        "programme_day": p.day,
        "programme_days": p.member.program_days,
        "latent_impairment": round(p.level, 4),
        "exercise": p.exercise,
        "inputs": p.inputs,
        "note": ("The trend across these sessions comes from the designed generator inputs "
                 "above; the unchanged pipeline measured the resulting signals. It is not an "
                 "observation of any person."),
    }


def run(args) -> int:
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.security import create_access_token
    from app.db.database import SessionLocal
    from app.db.models.audit import AuditAction
    from app.db.models.session import ExerciseType, Session as SessionModel, SessionStatus
    from app.main import app
    from app.sensing import model_store
    from app.sensing import provenance as prov
    from app.services import audit_service, report_service, sensing_service, session_service

    settings = get_settings()
    print(f"database  {_redacted(settings.database_url)}")
    if not _is_local(settings.database_url) and not args.yes:
        print("This database is not local. Re-run with --yes to write to it.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        if args.reset_demo:
            removed = reset_demo(db)
            print(f"reset     removed {removed['patients']} demo records, {removed['sessions']} "
                  f"sessions, {removed['devices']} demo devices")
            if not args.regenerate:
                return 0

        clinicians = visible_to(db, args.clinician_email)
        generator = generator_account(db)
        db.commit()
        token = create_access_token(generator.id, generator.role.value, generator.token_version)
        bundle, reason = model_store.get("bilateral")
        model_ref = f"{bundle.name}/{bundle.version}" if bundle else None
        if bundle is None:
            print(f"warning   activity model unavailable ({reason}); sessions will say so")

        schedule = plan(args.seed)
        only = {k.strip().upper() for k in args.only.split(",")} if args.only else None
        client = TestClient(app)
        totals = {"created": 0, "skipped": 0, "samples": 0, "packets_dropped": 0}
        t_run = time.perf_counter()

        for member in COHORT:
            if only and member.key not in only:
                continue
            first = min(p.started_at for p in schedule if p.member is member)
            patient, created = ensure_patient(
                db, key=member.key, name=member.name, preferred_name=member.preferred_name,
                age=member.age, operated_leg=member.operated_leg,
                provenance=prov.SYNTHETIC_DEMONSTRATION, program=member.program,
                program_days=member.program_days, planned_sessions=member.planned_sessions,
                recovery_start=first.astimezone(IST).date(),
                notes=(f"{LABEL_SYNTHETIC}. Fictional demonstration record ({GENERATOR_VERSION}). "
                       f"Trajectory: {TRAJECTORY_TEXT[member.trajectory]}"),
                actor=generator)
            ensure_assignment(db, patient.id, generator.id)
            for clinician in clinicians:
                ensure_assignment(db, patient.id, clinician.id)
            db.commit()
            print(f"\n{member.key} {member.name} ({member.trajectory}, {member.program_days} d) "
                  f"{'created' if created else 'exists'} as patient {patient.id}")

            for p in (x for x in schedule if x.member is member):
                existing = db.execute(select(SessionModel).where(
                    SessionModel.idempotency_key == p.key)).scalar_one_or_none()
                if existing is not None and existing.patient_id != patient.id:
                    raise SystemExit(f"idempotency key {p.key} belongs to another record; stopping")
                if existing is not None and existing.status is SessionStatus.COMPLETED:
                    totals["skipped"] += 1
                    continue
                if existing is not None:
                    # Left behind by an interrupted run: generated data only.
                    db.delete(existing)
                    db.commit()
                t0 = time.perf_counter()
                session = session_service.create_session(
                    db, patient=patient, exercise_type=ExerciseType(p.exercise), actor=generator,
                    idempotency_key=p.key)
                session.generation = _generation(p, args.seed, model_ref)
                session.notes = _session_notes(p)
                db.commit()
                sid = session.id
                stats = stream_synthetic(client, sid, p)
                end_through_api(client, token, sid, p.inputs["reported_pain"], _session_notes(p))
                db.expire_all()
                backdate(db, sid, p.started_at)
                session = db.get(SessionModel, sid)
                session.generation = {**session.generation, "stream": stats}
                db.commit()
                s = session.summary or {}
                mq = (s.get("movement_quality") or {}).get("mqi")
                asym = (s.get("bilateral") or {}).get("asymmetry_score")
                totals["created"] += 1
                totals["samples"] += stats["samples_generated"]
                totals["packets_dropped"] += stats["packets_dropped"]
                print(f"  S{p.index:02d} day {p.day:2d} {p.exercise:14s} level {p.level:.2f} -> "
                      f"MQI {mq} asym {asym} reps {s.get('repetitions')} "
                      f"conf {(s.get('confidence') or {}).get('percent')}% "
                      f"[{time.perf_counter() - t0:.1f}s]", flush=True)

            report = report_service.ensure_movement_report(
                db, patient, actor=generator, idempotency_key=f"{NAMESPACE}/{member.key}/report")
            db.commit()
            if report is not None:
                print(f"  report {report.id} ({report.status.value})")

        if args.public_replay and (not only or DSADS_KEY in only):
            if not dsads_available():
                print("\npublic replay skipped: the UCI DSADS files are not on this machine "
                      "(ml/data is not in git; see ml/README.md)")
            else:
                replayed = seed_public_replay(db, client, token, generator, clinicians, args.seed,
                                              model_ref)
                totals["created"] += replayed["created"]
                totals["skipped"] += replayed["skipped"]
                totals["samples"] += replayed["samples"]

        # Demo sources are never left looking connected.
        for device_id in (DEMO_DEVICE_ID, REPLAY_DEVICE_ID):
            sensing_service.mark_device_offline(db, device_id)
        audit_service.record(db, action=AuditAction.DEMO_DATA_SEEDED, entity_type="demo_namespace",
                             entity_id=NAMESPACE, actor_id=generator.id, seed=args.seed,
                             generator_version=GENERATOR_VERSION, created=totals["created"],
                             skipped=totals["skipped"])
        db.commit()
        print(f"\ndone      {totals['created']} sessions generated, {totals['skipped']} already present, "
              f"{totals['samples']} samples streamed, {totals['packets_dropped']} packets dropped "
              f"by design, {time.perf_counter() - t_run:.0f}s")
        return 0
    finally:
        db.close()


def seed_public_replay(db, client, token, generator, clinicians, seed: int, model_ref) -> dict:
    from sqlalchemy import select

    from app.db.models.session import ExerciseType, Session as SessionModel, SessionStatus
    from app.sensing import provenance as prov
    from app.sensing.processor import PIPELINE_VERSION
    from app.services import session_service

    daily_sports, to_device = _dsads_tools()
    recs = daily_sports._load_all()
    by_key = {(r.subject, r.source_activity, r.meta["segment"]): r for r in recs}
    subjects = sorted({r.subject for r in recs})
    patient, created = ensure_patient(
        db, key=DSADS_KEY, name=DSADS_NAME, preferred_name=None, age=None, operated_leg="LEFT",
        provenance=prov.PUBLIC_DATASET_REPLAY,
        program="Model reference recordings (public dataset, not a patient)", program_days=None,
        planned_sessions=None, recovery_start=None,
        notes=(f"{LABEL_REPLAY}. One replayed public recording per dataset subject, re-sent "
               "through the device pipeline. Healthy public subjects, not patients."),
        actor=generator)
    ensure_assignment(db, patient.id, generator.id)
    for clinician in clinicians:
        ensure_assignment(db, patient.id, clinician.id)
    db.commit()
    print(f"\n{DSADS_KEY} {DSADS_NAME} {'created' if created else 'exists'} as record {patient.id}")
    out = {"created": 0, "skipped": 0, "samples": 0}
    for subject in subjects:
        key = f"{NAMESPACE}/{DSADS_KEY}/{subject}"
        existing = db.execute(select(SessionModel).where(SessionModel.idempotency_key == key)
                              ).scalar_one_or_none()
        if existing is not None and existing.status is SessionStatus.COMPLETED:
            out["skipped"] += 1
            continue
        if existing is not None:
            db.delete(existing)
            db.commit()
        t0 = time.perf_counter()
        session = session_service.create_session(db, patient=patient, exercise_type=ExerciseType.WALK,
                                                 actor=generator, idempotency_key=key)
        s_seed = derived_seed(seed, DSADS_KEY, subject)
        session.generation = {
            "provenance": "PUBLIC_DATASET_REPLAY", "label": LABEL_REPLAY,
            "generator": "rehabsense-public-replay", "synthetic_generator_version": GENERATOR_VERSION,
            "seed": seed, "session_seed": s_seed, "source_dataset": DSADS_SOURCE,
            "dataset_subject": subject, "model_version": model_ref, "pipeline_version": PIPELINE_VERSION,
            "generation_timestamp": datetime.now(timezone.utc).isoformat(),
            "note": ("The activity model was trained on this dataset, this subject included: agreement "
                     "with the dataset labels checks that the device pipeline feeds the model "
                     "correctly. It is not a generalisation estimate and not hardware validation."),
        }
        session.notes = f"{LABEL_REPLAY}. Dataset subject {subject}; healthy public volunteer, not a patient."
        db.commit()
        sid = session.id
        stats = stream_dsads(client, sid, subject, by_key, to_device, s_seed)
        end_through_api(client, token, sid, None, session.notes)
        db.expire_all()
        session = db.get(SessionModel, sid)
        session.generation = {**session.generation, "segments": stats.pop("segments"), "stream": stats}
        db.commit()
        out["created"] += 1
        out["samples"] += stats["samples_generated"]
        s = session.summary or {}
        print(f"  {subject} replayed: {stats['samples_generated']} samples, "
              f"{(s.get('activity') or {}).get('windows')} model windows "
              f"[{time.perf_counter() - t0:.1f}s]", flush=True)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synthetic demonstration cohort through the real pipeline "
                    "(SYNTHETIC DEMONSTRATION DATA — NOT CLINICAL VALIDATION)")
    parser.add_argument("--clinician-email", action="append", default=[],
                        help="existing clinician account that should see the cohort (repeatable)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--only", default=None, help="comma-separated member keys, e.g. P01,P03")
    parser.add_argument("--reset-demo", action="store_true",
                        help="delete the demo namespace (only), then stop")
    parser.add_argument("--regenerate", action="store_true", help="with --reset-demo: generate again")
    parser.add_argument("--no-public-replay", dest="public_replay", action="store_false",
                        help="skip the UCI DSADS public-dataset replay record")
    parser.add_argument("--plan", action="store_true", help="print the schedule and stop")
    parser.add_argument("--yes", action="store_true", help="allow writing to a non-local database")
    args = parser.parse_args(argv)
    if args.plan:
        for p in plan(args.seed):
            print(f"{p.key:28s} {p.started_at.astimezone(IST):%Y-%m-%d %H:%M} day {p.day:2d} "
                  f"{p.exercise:14s} level {p.level:.2f} sev {max(p.inputs['left']['severity'], p.inputs['right']['severity']):.2f} "
                  f"var {max(p.inputs['left']['variability'], p.inputs['right']['variability']):.3f} "
                  f"move {p.inputs['movement_s']}s loss {p.inputs['packet_loss']:.3f}")
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
