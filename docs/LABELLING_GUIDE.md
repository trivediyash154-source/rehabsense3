# Labelling RehabSense recordings

Labels turn real hardware recordings into training data. Only labels that an
observer can give reliably are collected. There are deliberately no
diagnostic, prognostic or "recovery" labels.

## Before labelling

- Only **real** (non-simulated) sessions become training data. Simulated
  sessions can be labelled for UI testing but are excluded from every export.
- The patient must have an active **MODEL_TRAINING consent**
  (`PUT /api/patients/{id}/consent`) with a reference to the signed form.
  Without it, the session's raw samples expire under the retention policy and
  are never exported.
- Times are seconds from the session start, as shown in the session summary
  and the repetition table.

## Fields

| Field | What to record | Notes |
|---|---|---|
| `t_start`, `t_end` | The span the label applies to | Whole repetition, or one phase of it |
| `exercise_type` | What the patient was asked to do | Usually the session's exercise |
| `activity` | What they actually did, if different | e.g. a pause to stand, walking between sets |
| `repetition_index` | Which repetition (1, 2, …) | Counted by the observer, not copied from the detector |
| `side` | `LEFT` / `RIGHT` | For unilateral exercises or one-side observations |
| `movement_phase` | `rest`, `initiation`, `movement`, `peak`, `return` | Only when the phase boundaries are clearly visible (video helps) |
| `quality_rating` | 1–5, rubric below | Leave empty if unsure — an empty rating is better than a guess |
| `notes` | Free text | No identifying details |

## Quality rubric (observer rating, not a clinical score)

1. Could not complete the movement as instructed.
2. Completed with clear compensation (e.g. obvious weight shift, trunk lean,
   loss of balance, stopping mid-repetition).
3. Completed with minor, intermittent compensation.
4. Completed as instructed with small deviations.
5. Completed as instructed, smooth and controlled.

When two therapists label the same session, both labels are kept; agreement
between them is how the rubric's reliability is measured before any model is
trained on it.

## How labels are used

```
patient performs exercise
   → device records (raw samples stored, consent checked)
   → therapist labels repetitions / phases / quality
   → de-identified export (consented, non-simulated only)
   → training and evaluation on held-out *patients*
   → new model version (never overwrites the previous one)
```

A model trained on these labels is still a research model until it is
validated in a properly designed study.
