# RehabSense hardware-first ML architecture

Target hardware: **1 × ESP32, 2 × MPU6050 (LEFT and RIGHT), N force channels**
(N is configurable; FSR402 on a voltage divider is the expected sensor).

This document describes how sensor data travels from that device to the
interface, what the machine-learning components do and do not do, and how the
public datasets relate to the real device. The status of every claim is
explicit: **public-dataset performance is not RehabSense hardware performance,
and neither is clinical validation. Hardware and clinical validation: NOT
VALIDATED.**

---

## 1. End-to-end path

```
ESP32 (firmware/rehabsense_dual_imu)        simulator (DEV only, simulated: true)
  │  2× MPU6050 read in one tick, one timestamp       │
  │  force ADC channels                                │
  └──────── ws /ws/ingest/v2/{session} ────────────────┘
                     │  protocol v2 (docs/SENSOR_PROTOCOL_V2.md)
                     ▼
   validation (pydantic) ─ device key ─ simulation switch ─ protocol-mix guard
                     ▼
   stream integrity      app/sensing/stream.py
     ordering · duplicates · gaps · rate · jitter · drift · frozen IMU · latency
                     ├──► raw chunks (compressed ~1 s blocks) ──► sensor_sample_chunks
                     ▼
   calibration (8 checks)  app/sensing/calibration.py ──► device_calibrations
                     ▼
   bias/scale correction · per-IMU tilt (mounting-independent)  orientation.py
                     ▼
   window buffer (window from model bundle, stride from config)  windowing.py
                     ▼
   ┌─────────────────────────────┬─────────────────────────────┐
   │ activity model (sklearn)    │ signal processing           │
   │  features.py (shared w/ ml) │  bilateral.py  force_motion │
   │  inference.py               │  repetitions.py  quality.py │
   └──────────────┬──────────────┴──────────────┬──────────────┘
                  ▼                             ▼
     activity_results            movement_assessments · repetition_results
                  └──────────────┬──────────────┘
                                 ▼
              PostgreSQL / SQLite (same models, Alembic migrations)
                                 ▼
          /ws/live/{session}  hw_* events      REST /api/sessions/{id}/analysis …
                                 ▼
              Next.js  /workspace/hardware  (authenticated, role-checked)
```

Everything between the socket and the database is pure computation in
`backend/app/sensing/` (no I/O), wrapped by `services/hw_registry.py` for
broadcast and persistence. Inference runs on the server. The models are small
feature-based estimators, so moving inference to the edge later is possible but
not done (§10).

## 1b. Provenance: what counts as hardware data

`simulated: true` → `SIMULATED`. A device registered via
`POST /api/devices/register` and authenticated with its own key → `LIVE`.
Anything else → `UNVERIFIED`. Only `LIVE` sessions count as hardware evidence,
can become training data, baselines or pilot-dataset entries. (The previous
"not declared simulated = hardware" rule had already mislabelled 22
test-script devices; see docs/HARDWARE_VALIDATION_STATUS.md.)

## 2. Sensor representation

`app/sensing/channels.py` keeps the sides apart end to end:

```
0..5   left  ax ay az gx gy gz   (g, deg/s)
6..11  right ax ay az gx gy gz
12..   force channels, declared order and unit
```

A missing reading is NaN, never 0. The existing v1 `SegmentSample` (thigh/shin
per leg node) is unchanged; v2 has its own `DualSample` because the layout and
timing guarantees differ. One session holds one protocol only.

**No knee angle.** With one IMU per leg there is no second segment to subtract,
so v2 reports a *segment tilt* from the calibrated neutral pose and its range
as a **range-of-motion proxy**. v2 summaries set `rom_deg` and
`symmetry_index_pct` (v1 fields) to null instead of approximating them.

## 3. Synthetic data vs bilateral data

| Data | Bilateral? | Used for |
|---|---|---|
| Daily & Sports | **Yes**: real Xsens unit on each leg, recorded simultaneously | bilateral activity model, sanity checks of the bilateral metrics |
| PAMAP2 | No: one ankle IMU | single-IMU model, encoder pretraining |
| UCI HAR (Kaggle CSV) | No: waist phone, features only | stage-1 benchmark only, not deployable |
| RehabSense device | Yes, plus force | the eventual training and validation data |
| Simulator | Synthetic | development and tests only, never training |

A single-IMU recording is never duplicated or mirrored into a fake left/right
pair. Daily & Sports legs are used individually for the single-IMU model
because each one is a real, separate sensor.

## 4. Calibration (every wearing)

`DeviceCalibrator` workflow (calibration v2):

1. device connected (handshake)
2. **sensor health check** (1 s): each declared IMU present, not frozen,
   gravity-plausible; otherwise retried, never calibrated on
3. **neutral position**: the server *detects* 3 s of stillness on every
   healthy IMU (no timer assumption; fails after 20 s)
4. collect samples (the still window + 5 s of slow repetitions)
5. estimate per-sensor offsets / orientation (LEFT and RIGHT independently)
6. validate quality (eight checks below)
7. store: `device_calibrations` row with sequence number, session, device,
   timestamp and the exact sample windows used. `scripts/recompute_calibration.py`
   re-derives it from stored raw chunks; a test asserts the result matches.

Lifecycle: recalibration creates sequence n+1 and supersedes n
(`invalidated_at`, reason); a device reconnect marks the calibration stale
(`CALIBRATION_STALE`), with outputs flagged until recalibrated. The phase is
pushed to the device (`calibration_phase`), which drives its LED.

The eight checks: Each is PASS / WARN / FAIL / SKIPPED, with the thresholds stored
alongside:

1. IMU connectivity (≥ 95% readings, not frozen)
2. sampling rate (measured vs declared; ≤ 5% PASS, ≤ 15% WARN)
3. orientation (|g| plausibility; neutral gravity direction per IMU)
4. accelerometer baseline (offset, stillness)
5. gyroscope baseline (bias per axis, noise)
6. force sensor (presence, offset, noise, saturation, load response)
7. neutral position (stored gravity vector per IMU)
8. baseline movement (rotation axis per IMU, gyro RMS, tilt range)

No MPU6050 is assumed to match another: bias, scale and orientation are per
sensor. The rotation axis is learned from the movement itself, so the tilt does
not depend on how the strap was put on. The simulator straps each IMU at a
random orientation, and a test asserts that the tilt is recovered within 2.5°
(median).

## 5. Synchronisation and stream integrity

The two IMUs share a clock by construction: the same MCU reads them in the same
tick and stamps one timestamp. That is checked, not assumed:

* ordering and timestamp monotonicity (late samples dropped, counted)
* duplicates (retransmits recognised by `seq`) vs out-of-order arrivals
* gaps → missing samples, loss ratio
* measured rate (median interval) vs declared; jitter
* clock drift vs the server (lower-envelope regression, ≥ 30 s of data)
* frozen IMU (identical readings ≥ 25 samples) → treated as missing
* relative latency (arrival delay above the fastest observed packet; absolute
  one-way latency would need synchronised clocks)

## 6. Windowing

All device data reaches the model through one function,
`windowing.prepare_model_input` (moving-average anti-alias, then linear
resample). PAMAP2's 100 → 25 Hz conversion in training calls the same function.

The window length comes from the model bundle (what it was trained on). The
stride is server configuration (`HW_STRIDE_S`, default 0.5 s). The hardware
stream is resampled to the model's rate. The benchmark (§8) sweeps 1, 2 and
3 s windows and reports accuracy alongside the *response delay* each implies
(≈ window/2 + stride).

## 7. ML outputs, each with status and confidence

| Output | Method | Status values |
|---|---|---|
| Activity | sklearn model on orientation-invariant features | OK · LOW_CONFIDENCE · INSUFFICIENT_DATA · MODEL_UNAVAILABLE |
| Movement phase | heuristic on tilt (rest/initiation/movement/peak/return), **not a trained model** | per side, null when no reps yet |
| Bilateral asymmetry | normalised left/right differences, equal weights | OK · SINGLE_SIDE · NO_MOVEMENT · INSUFFICIENT_DATA |
| Force/motion | force-peak timing vs movement peak, consistency, side difference, phase means, correlation & lag | per channel; force symmetry only if channels on both sides |
| Repetitions | peak detection on tilt; gait cycles for walking; none for holds | — |
| MQI | transparent components, equal weights, ≥ 3 reps | OK · LOW_CONFIDENCE · INSUFFICIENT_DATA |

The activity model never invents a class it was not trained on. There is no
squat, sit-to-stand or knee-extension class, because no public dataset contains
them; the exercise is known from the session. A prediction below the bundle's
threshold is reported as LOW_CONFIDENCE, with the candidate kept separately and
never shown as the answer.

**RehabSense Movement Quality Index — research prototype.** Components:
symmetry, ROM proxy vs personal baseline, temporal consistency, smoothness
(SPARC), force consistency, repetition consistency. Equal weights over available
components, because there is no labelled data to fit weights; components that
cannot be computed are listed as unavailable, never imputed. `WEIGHTS` in
`quality.py` is where fitted weights go once therapist labels exist.

## 8. Public datasets → hardware: domain gap and adaptation

The gap, concretely:

| | Public data | RehabSense |
|---|---|---|
| Sensor | Xsens MTx / Colibri / phone | MPU6050 (noisier, ±4 g, ±500 °/s) |
| Placement | leg (D&S), dominant ankle (PAMAP2), waist (UCI) | shank or thigh, declared per IMU |
| Orientation | fixed per dataset | whatever the strap gives |
| Rate | 25 / 100 / 50 Hz | configurable, measured |
| Force | none | FSR402 load proxy |
| Activities | daily life / sport | rehabilitation exercises |

What is done about it now:

1. **Orientation-invariant features** (|a|, vertical/horizontal components
   relative to the window's gravity estimate, and the same for ω). The
   benchmark scores every model on randomly rotated test windows. Raw-axis
   features are included as a control to show why this matters.
2. **Robustness tests** for the specific differences above: rotation, 3× noise,
   residual gyro bias, accelerometer gain error, 5% clock error.
3. **Cross-dataset transfer test** (train on one dataset's sensors, test on the
   other's) as a direct measurement of how much a sensor/placement change costs.
4. **Domain block on every prediction**: training dataset, placement match, and
   `hardware_validated: false`.

What happens next (stages 4–6):

```
public datasets → pretraining / baseline           (stages 1-3, done)
       ↓
real RehabSense collection (consented, labelled)   (stage 4: export script, label tables)
       ↓
device calibration per wearing                      (done: §4)
       ↓
fine-tune / re-train on device data;
evaluate on held-out *patients*                     (stage 5)
       ↓
patient-specific baseline + calibration             (stage 6: personal baseline done)
```

The first public-dataset model is not the RehabSense model, and it is never
described as one.

### Benchmark results (full tables: `ml/reports/REPORT.md`, generated)

Headline findings, subject-independent on public data:

* **Raw sensor axes fail under remounting.** RF on raw-axis features scores
  0.943 macro-F1 but falls to **0.199** when test sensors are randomly
  rotated.
* **Orientation-invariant features alone lose posture** (sitting vs standing):
  0.829. Adding posture measured relative to the **calibrated neutral pose**
  (feature v2) restores **0.921**, unchanged under rotation (0.921) and robust to
  3× noise (0.915). On public data the neutral pose comes from one reserved
  standing recording per subject, excluded from evaluation, which emulates the
  device's calibration step.
* **Deployed:** random forest, invariant + neutral-pose features, 2 s window,
  25 Hz (selected by a rule fixed beforehand; gradient boosting scored 0.945
  but failed the latency budget at p95 156 ms). Deep models: 1D CNN 0.871,
  CNN-LSTM 0.896, PAMAP2-pretrained CNN 0.898. None were adopted.
* **Cross-dataset transfer collapses** (0.24 and 0.15 macro-F1). This is the
  size of the domain gap to expect on the RehabSense device until stage 5.
* **Preprocessing parity.** The same window replayed as a 100 Hz quantised,
  jittered device stream through the server's inference code agrees with the
  training-path prediction 98.4% of the time. Real public recordings
  replayed through the full device processor (calibration → windows → model)
  agree with their labels 96.3% of the time. That shows the device pipeline
  feeds the model correctly. It is not a hardware accuracy figure.

## 9. Personalisation

`patient_baselines` stores per-exercise reference metrics, taken from one or
more completed **real** sessions; simulated sessions are refused. Comparisons
are reported as *"Change from personal baseline"*: baseline, current, absolute
change, % change (null when the baseline is ~0), and a direction word
(higher / lower / similar). They are never worded as recovery, improvement or
deterioration.

## 10. Edge vs server inference

Server inference now. Measured in the server process: **4.7 ms p50 per window**
(features + model, one thread), about 36 KB allocated per call. However, the
loaded random forests take **≈ 220 MB (bilateral) and ≈ 460 MB (single-IMU)
of RAM**. That is acceptable on a server and impossible on an ESP32. Moving to the ESP32 would
need a much smaller model (e.g. a few dozen shallow trees or a tiny CNN with
int8 weights) plus on-device feature extraction. The orientation-invariant
feature set is cheap enough for that, and the deep `FusionNet` is kept
deliberately small (tens of thousands of parameters) so it stays an option.

## 11. Data, storage, consent

* Raw samples: compressed float32 chunks of ~1 s. Measured ≈ 240 KB per 45 s
  session with 2 IMUs + 2 force channels (≈ 19 MB/hour). Each chunk expires
  after `RAW_SAMPLE_RETENTION_DAYS` (30). `scripts/purge_raw_samples.py` or
  `POST /api/ml/retention/purge` (admin) deletes expired chunks.
* Consent: `data_use_consents` (MODEL_TRAINING). Granting marks the patient's
  real chunks `retain_for_training`; revoking clears it. Export
  (`scripts/export_training_dataset.py`) requires active consent, excludes
  simulated sessions, pseudonymises subjects with an HMAC of the server
  secret, and drops names, notes and dates.
* Access: every new route reuses the existing server-side authorisation (a
  record the caller may not see is a 404). Raw CSV export and labels are for
  the assigned clinician only. Audit rows are written for calibration, labels,
  baselines, consent, exports, purges and model registration.
* Models: `model_versions` registry; bundles are never overwritten and are
  hash-verified before loading.

## 12. Validation status

| Level | Status |
|---|---|
| Public-dataset performance | Evaluated, subject-independent (ml/reports) |
| Simulator | Pipeline mechanics only (ml/reports/simulator_evaluation.json): ROM proxy within ±1.3% (walking −9.4%), asymmetry monotonic with injected severity, every injected fault detected. Activity predictions on simulated data are not meaningful. |
| RehabSense hardware validation | **NOT VALIDATED**: no device recordings exist yet (pilot protocol: docs/PILOT_DATA_COLLECTION.md) |
| Clinical validation | **NOT VALIDATED** |
