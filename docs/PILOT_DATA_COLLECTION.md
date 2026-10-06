# RehabSense pilot data collection (real hardware)

This is the step that turns the public-dataset baseline into a RehabSense model
and produces the first **real hardware** performance numbers. Until it has been
run, hardware performance is **NOT VALIDATED**, whatever the public-dataset
scores say.

The protocol is defined once, in `backend/app/sensing/pilot.py`, and progress
against it is reported by `GET /api/ml/pilot-status`. That endpoint counts
only real, non-simulated sessions.

## Before the first subject

1. **Ethics and governance.** Institutional approval as required, a named data
   controller, a written retention period. The software enforces consent,
   retention and de-identification. It does not replace that approval.
2. **Hardware checks** (firmware/README.md). Run the I2C scanner (0x68 and
   0x69), confirm the measured 100 Hz rate on the Hardware page, confirm both
   FSRs respond to load.
3. **Placement.** Fix and document the IMU placement (e.g. lateral shank, 5 cm
   below the fibular head) and the strap. Declare it in `config.h`
   (`IMU_PLACEMENT`) so every recording carries it.
4. **Two-device check.** Record one session with the device, swap straps, and
   record again. Calibration must PASS both times. This checks the
   mounting-independence the pipeline claims.

## Per subject

| Step | Where | Pass condition |
|---|---|---|
| Consent (MODEL_TRAINING, with the signed form's reference) | Patients → consent / `PUT /api/patients/{id}/consent` | granted |
| Session per exercise | Hardware → Wait for real ESP32 | — |
| Calibration: stand still 3 s, then slow repetitions 5 s | device LED + Hardware page | calibration PASS or WARN |
| Exercise per protocol (reps / durations in `pilot.py`) | — | — |
| Activity segments (sit, stand, walk, stairs, lie) labelled with times | Session summary → labels | each segment labelled |
| Data validation | Hardware page → Data validation | verdict USABLE / USABLE_WITH_WARNINGS |
| Labels: repetition index, phases on ≥ 3 reps, quality rating | Session summary → labels | per docs/LABELLING_GUIDE.md |
| Repeat on a second day | — | `sessions_per_subject = 2` |

Video of each session, kept under the same consent, lets a second therapist
verify labels. Inter-rater agreement is reported before quality labels are
used for training.

## After collection

```bash
cd backend && python -m scripts.export_training_dataset --out ../ml/data/rehabsense_v1
ml/.venv/bin/python ml/scripts/finetune_rehabsense.py ml/data/rehabsense_v1
```

`finetune_rehabsense.py` reports:

* **A. zero-shot:** the public-pretrained model, unchanged, on held-out real
  subjects. This is the first *hardware validation* figure for the public
  model. Expect it to be much lower than the public-dataset score; the
  cross-dataset transfer benchmark (≈ 0.15–0.24 macro-F1) shows how large a
  sensor/placement change can be.
* **B. RehabSense-only** model, leave-one-subject-out.
* A new model version whose `validation_status.rehabsense_hardware` records
  the evaluation. The confidence threshold is re-derived on these data.

What still would not follow from a good result: clinical validity. That needs
a separate, properly designed study against a reference standard.

## Planned next model step

The deep `FusionNet` already has a configurable force branch (`n_force`) and a
shared per-IMU encoder pretrained on PAMAP2 (+0.027 macro-F1 over training
from scratch on the public benchmark). Once ≥ 10 subjects exist, the plan is:
initialise from the public encoder, train the force branch and fusion head on
RehabSense data, evaluate leave-subjects-out, and adopt it only if it beats
the feature model on held-out subjects.
