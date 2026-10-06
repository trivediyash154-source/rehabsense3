# RehabSense backend

FastAPI service for the RehabSense wearable rehabilitation platform: sensor
ingestion, signal processing, analytics, persistence, live streaming, reports
and authentication.

**Every ROM, symmetry and recovery figure this API returns is an estimated
decision-support indicator.** Not a diagnosis, not a clinical measurement, and
not a substitute for clinical evaluation. That framing is carried through the
API responses themselves, not only the documentation.

---

## Run it

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head                       # create/upgrade the schema
uvicorn app.main:app --reload --port 8000  # http://localhost:8000/docs
```

Seed a reproducible demo dataset by driving the real pipeline:

```bash
python -m scripts.seed_demo
```

That registers a clinician, creates a patient and streams five simulated
sessions through the production ingestion endpoint. Nothing is inserted
directly — every stored figure came out of the analytics chain.

Run a single session against a live server:

```bash
python -m app.simulator.sensor_simulator --session-id 1 \
    --exercise WALK --operated-leg LEFT --scenario ASYMMETRY --seed 42 --fsr
python -m app.simulator.sensor_simulator --list-scenarios
```

Tests:

```bash
pytest -q          # 62 tests: processing, API, authorisation, integration
```

---

## Architecture

```
app/
  api/          HTTP + WebSocket routing only
  core/         config, security, logging, errors
  db/           models, migrations target
  schemas/      request/response contracts
  services/     business logic (sessions, patients, reports, progress, devices)
  processing/   the maths: filters, calibration, fusion, segmentation,
                symmetry, recovery, confidence
  realtime/     WebSocket fan-out and event shapes
  hardware/     the wire protocol and per-leg connection state
  simulator/    a *client* of the production protocol
```

Routing never contains business logic; business logic never contains DSP;
DSP touches no database. `SessionProcessor` performs no I/O at all, which is
why the mathematics can be tested without a server or a socket.

### One pipeline, two sources

```
ESP32     ─┐
           ├─→ /ws/ingest/{id}?leg= → SessionProcessor → DB → /ws/live/{id} → frontend
simulator ─┘
```

There is no second code path for "real hardware". The simulator opens the same
socket, sends the same handshake and the same packets. The only difference is
the `simulated: true` flag a node declares about itself — which is why the API
can report `LIVE` vs `SIMULATED` honestly instead of guessing.

---

## The mathematics

Implemented exactly as specified in `ALGORITHMS.md`.

| Stage | Implementation |
|---|---|
| Calibration | Static gyro bias + accelerometer gravity normalisation over the first 2.5 s |
| Low-pass | 2nd-order Butterworth, 5 Hz cutoff |
| Fusion | Complementary filter, α = 0.98 |
| Drift bound | ZUPT during detected stance (FSR when declared, gyro magnitude otherwise) |
| Knee angle | `theta_shin − theta_thigh` (relative; no world reference needed) |
| ROM | `max − min` over a complete repetition or gait cycle |
| Symmetry | `LSI = operated / non-operated × 100%` over comparable aggregates |
| Recovery | `Σ wᵢ·sᵢ` — ROM .30, symmetry .25, compliance .20, cadence .15, inverse pain .10 |
| Confidence | Coverage, bilateral availability, delivery, calibration quality, repetition coverage |

**On scipy.** The spec pins `scipy==1.13.1` for one function: a 2nd-order
Butterworth low-pass. scipy has no wheel for current Python and fails to build
from source, so the filter is implemented directly in `processing/filters.py`
via the bilinear transform. It is the same filter, and `tests/test_processing.py`
verifies its magnitude response against the analytic Butterworth (−3.01 dB at
cutoff, flat passband, 12 dB/octave asymptotic roll-off) rather than assuming it.

**Two things the maths refuses to do:**

- Symmetry is computed only from *comparable* aggregates — peak repetition ROM
  or stance time. Instantaneous knee angles are never used: the limbs are
  phase-shifted, so at any single moment one is flexing while the other
  extends, and their ratio means nothing.
- A one-limb session returns `symmetry_index_pct: null`, not 100%. There is no
  symmetry to report, and saying so is more useful than inventing a number.

---

## API

The contract documented in `API_SPEC.md` is preserved exactly:

```
POST /api/patients            GET /api/sessions?patient_id=
GET  /api/patients            GET /api/sessions/{id}
GET  /api/patients/{id}       GET /api/sessions/{id}/metrics
POST /api/sessions            GET /api/sessions/{id}/reps
POST /api/sessions/{id}/end   GET /api/sessions/{id}/report
GET  /api/health              GET /api/sessions/{id}/report.csv
```

Product-level additions:

```
GET  /api/patients/{id}/overview          GET  /api/sessions/{id}/replay
GET  /api/patients/{id}/progress          GET  /api/devices
GET  /api/patients/{id}/progress/compare  GET  /api/exercises
GET  /api/patients/{id}/timeline          GET  /api/notifications
GET  /api/patients/{id}/passport          POST /api/reports/{id}/generate
POST /api/auth/register|login|refresh     POST /api/reports/{id}/share
GET  /api/me                              GET  /api/health/{database,websocket,analytics}
```

Every path is also served under `/api/v1/…` so clients can move to a versioned
prefix without a breaking change.

### WebSockets

```
ws://host/ws/ingest/{session_id}?leg=LEFT|RIGHT   devices and the simulator
ws://host/ws/live/{session_id}                    dashboards
```

`connection_status`, `metric_update`, `rep_event` and `risk_flag` keep their
documented shapes. `calibration_status`, `session_status`, `device_status`,
`signal_quality`, `report_ready` and `heartbeat` are additions — new types, not
changes to existing ones, so an older client keeps working.

---

## Hardware v2 (dual-IMU + force)

```
/ws/ingest/v2/{session_id}     one ESP32: LEFT + RIGHT MPU6050, N force channels
```

`app/sensing/` holds the v2 pipeline (pure computation): stream integrity,
8-check calibration, mounting-independent tilt, windowing, versioned features
shared with `ml/`, activity inference from verified model bundles, bilateral
asymmetry, force/motion, repetitions and phases, the Movement Quality Index
(research prototype) and personal-baseline comparison.
`services/hw_registry.py` broadcasts `hw_*` events and persists results.

```
GET  /api/sessions/{id}/analysis | activity | calibration | recording | recording.csv
GET/POST /api/sessions/{id}/labels           POST /api/sessions/{id}/simulate-hardware
GET/POST /api/patients/{id}/baseline         GET/PUT /api/patients/{id}/consent
GET  /api/ml/models  /api/ml/pipeline        POST /api/ml/retention/purge (admin)
```

New tables (migration `75b9b8c873bd`): `device_calibrations`,
`sensor_sample_chunks`, `activity_results`, `movement_assessments`,
`repetition_results`, `model_versions`, `session_labels`,
`patient_baselines`, `data_use_consents`.

Scripts: `scripts.register_model`, `scripts.purge_raw_samples`,
`scripts.export_training_dataset`.

Configuration (`.env`): `ML_MODEL_DIR`, `ML_ACTIVITY_MODEL[_VERSION]`,
`ML_ACTIVITY_MODEL_SINGLE[_VERSION]`, `HW_WINDOW_S`, `HW_STRIDE_S`,
`HW_CALIBRATION_STILL_S`, `HW_CALIBRATION_MOVEMENT_S`,
`ALLOW_SIMULATED_DEVICES`, `DEVICE_INGEST_KEY`, `STORE_RAW_SAMPLES`,
`RAW_SAMPLE_RETENTION_DAYS`.

See [../docs/HARDWARE_ML_ARCHITECTURE.md](../docs/HARDWARE_ML_ARCHITECTURE.md)
and [../docs/SENSOR_PROTOCOL_V2.md](../docs/SENSOR_PROTOCOL_V2.md).

---

## Security

- Argon2id password hashing; plaintext is never stored or logged.
- JWT access/refresh tokens with a per-user version, so logout invalidates
  every outstanding token.
- Authorisation is enforced server-side against the database. A clinician role
  is not sufficient — an **ACTIVE assignment to that patient** is required.
- A record the caller may not see returns **404, not 403**, so the API never
  confirms the existence of other people's data.
- Clinician-only fields (notes, signal diagnostics) are absent from
  patient-facing payloads. The server omits them; the UI is not trusted to hide
  them.
- Share links are random tokens stored only as a hash, with expiry, revocation
  and a view count. They expose patient-visible sections only.
- CORS is an explicit allow-list, never a wildcard. With `DEBUG=false` the
  startup lifespan calls `assert_production_safe()`, which refuses to boot on a
  default or short `SECRET_KEY`, a `*` entry, an empty list, a malformed origin,
  or a plaintext `http://` origin that is not loopback. Configuration mistakes
  fail loudly at start rather than presenting later as an unexplained browser
  error — or not at all.
- Audit rows carry identifiers and outcomes, never note bodies or credentials.

---

## Data model

`PATIENT · SESSION · METRIC_SNAPSHOT · REP_EVENT · RISK_FLAG` are preserved,
plus `USER`, `PATIENT_ASSIGNMENT`, `DEVICE`, `SENSOR`, `SESSION_DEVICE_LINK`,
`EXERCISE`, `EXERCISE_PLAN(_ITEM)`, `NOTIFICATION`, `REPORT`, `REPORT_SHARE`
and `AUDIT_LOG`.

For v1 (per-leg) sessions, raw 100 Hz samples are **not** persisted — only
chart-ready snapshots (~1/s) and discrete events. For v2 (dual-IMU) sessions,
raw samples *are* stored as compressed ~1 s chunks with an expiry date, so
that consented real recordings can become training data; see the retention
section of docs/HARDWARE_ML_ARCHITECTURE.md.

### Consistency

A completed session's `summary` is written once and every surface reads it:
dashboard, receipt, report, CSV and comparison all return the same numbers, and
`analytics_version` records which formulas produced them. `tests/test_hardware_integration.py`
asserts the session, report and replay agree.

---

## Configuration

See `.env.example`. In production the app refuses to start with the development
secret or a key under 32 bytes.

`CORS_ORIGINS` accepts a comma-separated string or a JSON array. Set it to the
origin the frontend actually runs on — a browser silently blocking the health
probe is indistinguishable from the backend being down.

---

## Known limitations

- Calibration performs the static-bias and normalisation stages. Full
  mechanical (functional) alignment is a later phase and is reported as such
  rather than silently claimed.
- Compliance and pain default to their documented neutral values until a
  prescription module and patient-reported input exist; both are flagged
  `available: false` so the interface can say so instead of implying they were
  measured.
- Trend analysis is a linear fit, as specified for the MVP.
- The live registry is in-process: a restart drops in-flight sessions, and
  ending one then rebuilds its summary from persisted rows. Multi-worker
  deployment needs a shared bus first.
- No clinical validation has been performed. Accuracy against a goniometer or
  optical reference is unmeasured.
