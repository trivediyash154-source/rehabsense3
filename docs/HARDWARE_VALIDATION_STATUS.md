# RehabSense hardware validation status

Audit date: 2026-10-06. Repository state: one commit (`38ccdb9`, initial
prototype) plus uncommitted work (protocol v2, sensing pipeline, ML, firmware).

## Headline

**SOFTWARE READY FOR PHYSICAL VALIDATION · NOT PHYSICALLY VALIDATED**

- PHYSICAL HARDWARE TESTED: **0**
- PHYSICAL_REGISTERED recordings: **0**
- HUMAN-LABELED PHYSICAL RECORDINGS: **0** (no gold set exists, and none was manufactured)

(The scratch PostgreSQL database used for the deployment audit holds one
PHYSICAL_REGISTERED recording with **0 samples**, integrity FAIL: an
artifact of a key-handshake check made before recordings were changed to
start with the first stored sample. It is not evidence; see
POSTGRESQL_VALIDATION.md.)

### ML status

```
MODEL IMPLEMENTED:                  YES
PUBLIC DATASET VALIDATED:           YES
REAL REHABSENSE HARDWARE VALIDATED: NO
HUMAN-LABELED PHYSICAL DATA:        0
CLINICAL VALIDATION:                NO
```

### Deployment status (DEPLOYMENT_AUDIT.md)

```
POSTGRESQL:         TESTED (16.2, local server) · managed instance NOT TESTED
API DOCKER IMAGE:   IMPLEMENTED · NOT TESTED (no Docker daemon)
VERCEL:             DEPLOYED (frontend-only, BACKEND_ORIGIN=none) · https://rehabsense-platform.vercel.app
OBJECT STORAGE:     TESTED with moto (S3 API emulation) · real bucket NOT TESTED
FIRMWARE WSS:       compiles · NOT TESTED on a board
```

**No component has been validated on physical hardware.** There is no
recording from an ESP32 + 2× MPU6050 + force sensor anywhere in this
repository or its databases. Everything below is implemented and tested
with synthetic data, public datasets, or host-side compilation. "Tested"
never means "tested on the device".

### Evidence found during the audit

- `backend/rehabsense.db` (the development database) lists **22 devices of
  kind `HARDWARE` and 10 sessions of mode `LIVE`**. None are physical
  devices. They are protocol-v1 test scripts (firmware strings
  `sim-1.0.0`, `load-1.0.0`, `x`; ids `sim-17-left`, `load-43-right`,
  `bad-01`, `nan-01`) that omitted `simulated: true`. The backend used to
  treat "not declared simulated" as "hardware". That rule is replaced:
  only a registered device authenticated with its own key is `LIVE`;
  anything else is `UNVERIFIED`. Migration `d1c0cc763b9e` relabels
  existing rows (verified on a copy of that database: 22 → `UNVERIFIED`,
  10 sessions → `UNVERIFIED`). The original file was not modified.
- No device has ever been registered with a key (the mechanism is new).

## Status legend

| Status | Meaning |
|---|---|
| IMPLEMENTED | code exists; exercised by unit/integration tests on constructed inputs |
| SIMULATED | verified end to end with the dual-IMU simulator (synthetic kinematics) |
| DATASET_VALIDATED | evaluated on public datasets (not RehabSense hardware) |
| PHYSICALLY_VALIDATED | verified on a registered RehabSense device: **none** |
| NOT_VALIDATED | no meaningful evidence yet |

## Components

| Component | Status | Evidence | Remaining Validation |
|---|---|---|---|
| Firmware: build | IMPLEMENTED | Compiles for ESP32 (incl. WHO_AM_I / config read-back evidence in hello) (arduino-esp32 3.3.12, `esp32:esp32:esp32`, WebSockets 2.7.2) with `--warnings all`, zero warnings; also with 0 force channels @ 50 Hz and 3 @ 200 Hz. `firmware/build_check.sh` | Flash a real board |
| Firmware: JSON frames | IMPLEMENTED | `rs_frames.h` compiled on the host (`-Wall -Werror`); hello/data/status frames, incl. null IMU, NaN→null, no-force, overflow refusal, parsed by the canonical models (`test_protocol_conformance.py`) | Capture frames from a real board and replay them through the same test |
| Firmware: I2C init, WHO_AM_I, ±4 g / ±500 °/s / DLPF config with read-back | IMPLEMENTED | Code review only | I2C scanner shows 0x68 + 0x69; serial log shows config read-back OK on both |
| Firmware: fixed-rate sampling task, single timestamp per tick | IMPLEMENTED | Code review + compile | Measured rate/jitter on the Hardware page with a real board, 10+ min |
| Firmware: ring overflow / I2C failure / IMU re-init counters | IMPLEMENTED | Code + status frame schema test | Unplug one IMU mid-session: `RIGHT_IMU_UNAVAILABLE` (NO_READINGS) and rising `i2c_errors_right` must appear |
| Firmware: reconnect, `SESSION_ENDED` / auth halts, LED from `calibration_phase` | IMPLEMENTED | Code review; server side tested | Kill Wi-Fi mid-session; end session from UI; wrong key |
| Protocol v2 (canonical schema, one representation) | IMPLEMENTED | Pydantic models → generated JSON Schema; golden examples; firmware, simulator, storage, ML channel order checked against it | Real-board frames |
| Device provenance (register / per-device key / UNVERIFIED) | IMPLEMENTED | Integration tests: wrong key refused, registered device declaring simulated refused, unregistered → UNVERIFIED, only LIVE retained/exported | Register the physical board; first LIVE session |
| Ingestion: validation, duplicates, out-of-order, gaps, frozen IMU, saturation, impossible values | SIMULATED | Unit tests on constructed streams; simulator scenarios (PACKET_LOSS, DUPLICATES, FROZEN_LEFT, RIGHT_IMU_DROPOUT, …); every injected fault detected (`ml/reports/simulator_evaluation.json`) | Real loss/jitter profile over Wi-Fi |
| Sampling-rate measurement (requested / median-interval / effective, jitter, drift, per-side & per-force availability) | SIMULATED | Unit test: 10% packet loss → median 100 Hz, effective ≈ 90 Hz; drift test 500 ppm; real-time E2E drift −14.9 ppm (host clock) | Real ESP32 crystal drift; effective rate under Wi-Fi load |
| Explicit `LEFT/RIGHT_IMU_UNAVAILABLE`, `FORCE_CHANNEL_UNAVAILABLE` | SIMULATED | Unit + integration tests (missing, frozen, disconnected, not declared); no substitution anywhere | Physically disconnect each IMU and each FSR |
| Calibration workflow (health → detected stillness → movement → 8 checks → stored with windows) | SIMULATED | Tests: phases reach the device in order; frozen sensors retried and never calibrated; no stillness → FAILED with reason; per-sensor gyro bias recovered (±0.15 °/s) under random mounting | Two real MPU6050s: compare offsets across days and re-straps |
| Calibration reproducibility | SIMULATED | `scripts/recompute_calibration.py` re-derives a stored calibration from stored raw chunks; test asserts max difference < 1e-3 | Same on a real recording |
| Calibration lifecycle (sequence, supersede, stale on reconnect) | IMPLEMENTED | Integration test | — |
| Mounting-independent tilt / ROM proxy | SIMULATED | Tilt within 2.5° median of simulated truth under random mounting; ROM proxy within ±1.5% (repetitions), **−9.4% walking** | Compare against a reference (goniometer / optical) on a person |
| Repetition & phase detection | SIMULATED | Counts within 1–2 of simulated cycles; phases are a heuristic, not a trained model | Therapist-labelled real repetitions |
| Bilateral asymmetry | SIMULATED | Monotonic in injected severity (squat, walk, sit-to-stand) | Real bilateral recordings with known conditions |
| Force/motion analysis | SIMULATED | Synthetic FSR model only | Real FSR402 response, load-response check at calibration |
| Movement Quality Index | NOT_VALIDATED | Definition frozen (SHA-256 in docs/MQI.md); simulator characterisation: decreases monotonically with asymmetry, insensitive up to 4× noise, MQIs from different component sets not comparable (enforced) | Real-data noise/repeatability, therapist ratings, statistics (docs/MQI.md §5) |
| Preprocessing parity (training path = device path) | DATASET_VALIDATED | Shared `prepare_model_input`; public windows replayed as 100 Hz device frames: 98.4% prediction agreement; full processor replay of real public recordings: 95.6% agreement with labels | Real device recordings through the same path |
| Activity model (bilateral RF, 2 s, 25 Hz) | DATASET_VALIDATED | Daily & Sports, subject-independent: macro-F1 0.921, rotation-invariant (`ml/reports/REPORT.md`) | **Hardware: NOT_VALIDATED.** Cross-dataset transfer collapses to 0.15–0.24 macro-F1, so expect a large drop until evaluated/fine-tuned on device data |
| Activity on simulator data | NOT_VALIDATED | Simulated walking is classified `other_exercise`: simulator kinematics are not real gait | Not meaningful by design |
| Recording provenance (SIMULATED / PUBLIC_DATASET_REPLAY / PHYSICAL_UNVERIFIED / PHYSICAL_REGISTERED) | IMPLEMENTED | Decided at handshake from authentication; enforced in export, retention, baselines, pilot status, finetune loader, report generator (tests) | First PHYSICAL_REGISTERED recording |
| Research recording: lossless raw storage, metadata, packet receive log | SIMULATED | Export test: device timestamps exact, losses kept as seq gaps, unavailable IMU kept as NaN, packet log present | Real recording |
| Research export (manifest + SHA-256, RAW vs DERIVED, labels vs predictions) | SIMULATED | Export/verify tests incl. tamper detection; training export read by the ML loader in a test | Export of a real recording |
| Recording integrity (flag, never repair) | SIMULATED | Impossible value → integrity FAIL while raw value stays stored | Real recording |
| Event markers (DEVICE / SERVER / USER sources, time basis + uncertainty) | SIMULATED | Device `event` frame lands on DEVICE_TIME; sensor_failure/recovered markers on dropout | Real device events; user-marker uncertainty on real Wi-Fi |
| Clock model (offset, drift, jitter, arrival delay; NOT_REAL_TIME) | SIMULATED | 3× replay reported NOT_REAL_TIME, never as drift; 500 ppm synthetic drift measured ±30 ppm | ESP32 crystal drift over ≥ 10 min |
| Human labels (SILVER / GOLD by a second human) | IMPLEMENTED | Tests: labeller cannot self-confirm; predictions never appear in labels.json | First therapist labels |
| Force units (adc_norm vs N with calibration_ref) | IMPLEMENTED | Protocol rejects N without calibration_ref; columns carry the unit | Force calibration against a reference (docs/FORCE_CALIBRATION.md) |
| Physical validation report generator | IMPLEMENTED | Refuses non-physical recordings; items without evidence → NOT TESTED (test) | Run on the first real recording |
| Database (SQLite) | IMPLEMENTED | 208 backend tests; migrations up/down/up; `alembic check` clean | — |
| Database (PostgreSQL) | IMPLEMENTED | Offline DDL generated and reviewed (enum `ADD VALUE`, `BYTEA`, enum drops on downgrade) | Run migrations + tests against a live PostgreSQL |
| Research recording mode, markers, research record | SIMULATED | Integration test: consent required; retained only for registered devices; markers on the device clock | First real research session |
| Data validation report | SIMULATED | Per-session verdict with provenance; offline re-validation from stored chunks | Real recordings |
| Frontend hardware page | IMPLEMENTED | Typecheck, lint, production build | Viewed in a browser against a real device |
| Clinical validity | NOT_VALIDATED | None | A designed clinical study |

## Hardware → ML domain gap

Public datasets (UCI HAR, PAMAP2, Daily & Sports) are **not** RehabSense
hardware data: different sensors, placements, orientation, rates, and no
force sensor. A 0.92 macro-F1 on Daily & Sports does not mean the
RehabSense device is 92% accurate. The intended path:

```
public-dataset pretraining        done (DATASET_VALIDATED)
→ RehabSense hardware collection  ready: research recording mode, pilot protocol
→ domain validation               ready: finetune_rehabsense.py (zero-shot on held-out subjects)
→ optional fine-tuning            ready: same script; FusionNet force branch waiting for data
→ hardware-specific evaluation    NOT DONE: needs ≥ 3 consented subjects on a registered device
```

## Stop condition

Physical hardware has not been available in this work. The software side is
finished up to the physical-validation boundary; the remaining items in the
table above all require the board. The procedure is
docs/PHYSICAL_HARDWARE_CHECKLIST.md, and its output is the generated
docs/PHYSICAL_VALIDATION_REPORT.md, which does not exist yet because no real
recording exists.

## First physical checks to run (in order)

1. `firmware/build_check.sh`, flash, I2C scanner: 0x68 and 0x69.
2. Register the board (`POST /api/devices/register`), put the key in `config.h`.
3. 10-minute static recording: effective rate, jitter, loss, drift, per-IMU
   availability, saturation. Record the numbers here, unrounded.
4. Unplug the right IMU, then one FSR, during a session: the matching
   `*_UNAVAILABLE` alerts must appear; nothing may be substituted.
5. Calibrate, re-strap, calibrate again: per-sensor offsets and the
   recompute check.
6. Pilot collection per docs/PILOT_DATA_COLLECTION.md.

Only after step 3 can any row move to PHYSICALLY_VALIDATED, and only for
what that step measured.
