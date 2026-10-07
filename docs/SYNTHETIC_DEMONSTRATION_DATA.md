# Synthetic demonstration data

> **SYNTHETIC DEMONSTRATION DATA — NOT CLINICAL VALIDATION.**
> Every record described here is generated or replayed. None of it comes from a patient or
> from RehabSense hardware, and none of it is evidence that RehabSense works clinically.
> RehabSense is a research prototype and not a medical device.

## Why it exists

The workspace (overview, patients, progress, sessions, reports, research) is built to display
recorded sessions. Until the ESP32 hardware has been validated on people, there is nothing to
show, and empty screens make the system hard to demonstrate or to review.

The demonstration cohort fills that gap. It does so **inside the real architecture**:
- the same database tables and ingestion socket;
- the same calibration, ML model, analytics and report builder.

Nothing is drawn by the frontend. The pages read what the pipeline stored. If the demo data
changes, the pages change.

## What is in it

| Key | Record | Programme | Days | Sessions | Trajectory (designed) |
|---|---|---|---|---|---|
| P01 | Synthetic demo · Aarav | Lower-limb rehabilitation | 60 | 21 of 24 planned | Strong improvement |
| P02 | Synthetic demo · Riya | Bilateral movement rehabilitation | 30 | 13 of 15 | Moderate improvement |
| P03 | Synthetic demo · Kabir | Mobility and gait | 20 | 9 of 10 | Stable |
| P04 | Synthetic demo · Ananya | Lower-limb rehabilitation | 15 | 8 of 8 | Rapid early improvement, then plateau |
| P05 | Synthetic demo · Dev | Movement symmetry | 20 | 10 of 12 | Early improvement, then decline |
| DSADS | Public dataset reference · UCI DSADS | Model reference recordings (not a patient) | — | 8 | Public recordings, one per subject |

There are 69 sessions in total, covering five exercises: squat, walking, sit-to-stand,
step-up and knee extension. Each synthetic session streams about 45–80 s of 100 Hz
dual-IMU and heel-force samples. About 432,000 samples are generated, and about 428,000 are
stored after the designed packet loss.

The names are fictional and every one is marked "Synthetic demo". There are no emails, phone
numbers or addresses. The records have no sign-in account.

### What the pipeline measured

These values come from the unchanged pipeline, from the default seed. "Start" is the mean of
a record's first two sessions; "current" is the mean of its last two.

| Record | MQI start → current | Asymmetry start → current | Status (rule below) |
|---|---|---|---|
| Aarav | 70.2 → 90.8 | 38.6% → 15.1% | Improving |
| Riya | 74.1 → 84.5 | → 21.1% | Improving |
| Kabir | 88.1 → 86.6 | ~22% | Stable |
| Ananya | 72.7 → 86.5 | → 17.6% | Completed (programme ended) |
| Dev | 83.5 → 75.8 | 29.3% → 28.8% | Needs attention |

Dev is there to show that RehabSense does not always report improvement.

The status rule is a stated rule over these indicators (`STATUS_RULE` in
`backend/app/services/movement_analytics.py`). It is an observation about stored data, not
a clinical assessment.

## How it is generated

`backend/scripts/seed_demo_data.py` runs every session through the same path a device uses:

```
generator inputs (per session, designed)          replayed public recording (DSADS)
        │ app/simulator/dual_imu.py                          │ ml/rehabsense_ml/datasets
        ▼                                                    ▼
  ws /ws/ingest/v2/{session}   hello: simulated=true, data_source=SYNTHETIC_DEMONSTRATION
                                                  (or PUBLIC_DATASET_REPLAY)
        ▼
  handshake + provenance → stream checks → calibration → windowing → activity model
  → bilateral asymmetry → repetitions → MQI → PostgreSQL (chunks, results, trace)
        ▼
  POST /api/sessions/{id}/end      (the endpoint a clinician's "End session" calls)
        ▼
  report_service.ensure_movement_report  (the builder behind "Generate report")
```

The socket and the end endpoint run inside the script's own process (FastAPI's test client
against the real app), pointed at whichever database `DATABASE_URL` names.

### Where the trajectories come from

Each record has a designed trajectory: a latent "impairment" level for each programme day,
with session-to-session noise. That level only sets the **inputs** of the parametric motion
model. For the operated side:

- **Severity:** shorter range and slower movement.
- **Rep-to-rep variability:** how much range and timing vary from one repetition to the next.
- **Tremor:** a small 4–8 Hz oscillation.
- **Timing lag.**

On top of those, each session also gets packet loss, sensor noise, session length and a
generated pain score.

Every input is stored on its session (`sessions.generation`) and shown on the session page.
The pipeline then measures the signals as it would measure any device:
- MQI, asymmetry, repetitions and confidence are its outputs, not inputs;
- no stored value was edited.

An "improving" chart therefore shows that the pipeline responds to the designed change. It
does not show that anyone improved.

The two realism inputs (`SideConfig.variability`, `SideConfig.tremor_deg`) default to 0. At
0 the motion model is bit-for-bit the original; a test checks this.

### Reproducibility

- **Fixed seed:** the seed (default `20261007`) and the generator version
  (`synthetic-demo-v1`) fix every generator input and every sample. A rerun with the same
  seed produces the same samples.
- **Deterministic pipeline:** the same samples produce the same measurements.
- **Calendar dates:** only the dates move. Sessions are placed on programme days counted
  back from the day of generation.
- **What each session records:** `synthetic_generator_version`, `seed`, `session_seed`,
  `source_dataset`, `model_version`, `pipeline_version`, `generation_timestamp`, the
  trajectory, the programme day and all inputs.

## Source datasets and models

| Source | Used for | Status |
|---|---|---|
| Parametric kinematic model (`app/simulator/dual_imu.py`) | All five synthetic records | Synthetic; no human data. |
| UCI Daily and Sports Activities (Barshan & Altun, CC BY 4.0), leg units | The DSADS reference record: one replayed recording per subject (standing, walking, stairs up and down, cycling, sitting) | Public healthy volunteers. Local only (`ml/data` is not in git); skipped when absent. |
| PAMAP2, UCI HAR | Not used here | Single ankle or waist IMU; there is no second side to replay. |
| `activity_bilateral/v1` (RandomForest, DSADS-trained) | Activity classification in every session | Public-dataset evaluated. Not validated on RehabSense hardware or clinically. |

**Public dataset performance ≠ RehabSense hardware performance.**

On the DSADS replays, the model agrees with the dataset's labels on about 98% of scored
windows. Those subjects were in its training data. The figure checks that the device
pipeline feeds the model correctly. It is not an accuracy estimate.

On synthetic squats and walking, the model mostly answers "other exercise" or "standing".
That is reported as-is: those labels are model output on generated signals, with no ground
truth.

## Provenance

| Value | Meaning | Counts as hardware evidence |
|---|---|---|
| `PHYSICAL_REGISTERED` | Registered RehabSense device, authenticated with its own key | Yes, the only one |
| `PHYSICAL_UNVERIFIED` | Not declared simulated, not authenticated | No |
| `SYNTHETIC_DEMONSTRATION` | This cohort | No |
| `PUBLIC_DATASET_REPLAY` | Public recordings re-sent through the device pipeline | No |
| `SIMULATED` | The developer simulators | No |

Where provenance is stored:
- **Sessions:** at the handshake, from what the sender declares and authenticates, never
  from the data.
- **Records:** `patients.provenance` (`NULL` for a real person's record).
- **Devices:** inferred from the device's latest recording.

Where the UI shows it:
- a badge on every page;
- a "Synthetic demonstration environment" banner in the workspace shell;
- a labelled topbar.

Every PDF page carries "SYNTHETIC DEMONSTRATION DATA — NOT CLINICAL EVIDENCE" and
"RehabSense is a research prototype and not a medical device."

The demo devices are `DEMO-ESP32-001` (synthetic) and `DEMO-REPLAY-DSADS`. Both are simulators
by declaration and are never shown as connected physical boards. The live lab keeps saying
**WAITING FOR REAL ESP32** until a registered device streams.

## Regenerate, reset

Run from `backend/` with `DATABASE_URL` set. A database that is not local also needs `--yes`.

```bash
python -m scripts.seed_demo_data --plan                        # schedule only, writes nothing
python -m scripts.seed_demo_data --clinician-email you@clinic.example
python -m scripts.seed_demo_data --reset-demo                  # remove the cohort
python -m scripts.seed_demo_data --reset-demo --regenerate --clinician-email you@clinic.example
```

### Idempotent

Records are keyed by `demo_key` (`synthetic-demo/v1/P01`) and sessions by idempotency key.
A second run skips everything that is already complete. A session left behind by an
interrupted run is regenerated.

### Isolated

`--reset-demo` deletes only records whose `demo_key` is in the namespace and whose provenance
is synthetic or replay. If any completed session under those records is not generated data,
it refuses and deletes nothing. There is no "delete all" path.

### Accounts

The script never creates or edits a real account.
- `--clinician-email` must name an existing clinician. It only adds an assignment, so that
  clinician can see the cohort.
- Generated rows are written by `synthetic-demo-generator@example.com`. That account has no
  password and no sign-in identity.
- Seeding and resetting are audited (`DEMO_DATA_SEEDED`, `DEMO_DATA_RESET`).

## Why it must not be treated as clinical evidence

- **No people:** no person was measured. The trajectories were designed, and the pipeline
  measured signals that a model made.
- **No hardware:** the motion model is physically consistent, but it is not the RehabSense
  device on a body. Sensor placement, soft-tissue motion, real gait impacts and real noise
  are not reproduced.
- **Unvalidated indicators:** MQI and the asymmetry score are research indicators (see
  `docs/MQI.md`). Neither is validated against clinical outcomes.
- **Training-set agreement:** activity labels on synthetic data have no ground truth. On the
  public replay, agreement is measured on the model's own training subjects.

## Limitations

- **Exercise mix:** walking scores a higher MQI and higher asymmetry than a squat at the same
  designed level, so a mixed programme zig-zags. This is real behaviour of the indicators.
- **Unilateral exercises:** for step-up and knee extension, only the range varies rep to rep;
  the set timing is fixed.
- **Personal baseline:** none is set, so MQI uses five components throughout. Its MQIs
  stay comparable session to session, but are not comparable with a baseline-based MQI.
- **Replay speed:** sessions are streamed faster than real time. The stream report correctly
  marks the clock `NOT_REAL_TIME`.
- **Live replay:** the Live Lab replays stored pipeline output on the session clock. It shows
  what was computed, not a new computation.
