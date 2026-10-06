"""Pilot data-collection protocol for the first real RehabSense recordings.

The protocol is data, so the tracker, the UI and the documentation read one
definition. Targets are planning numbers for a feasibility pilot (enough for
subject-independent evaluation with leave-one-subject-out), not a powered
clinical study.
"""

from __future__ import annotations

PILOT_PROTOCOL = {
    "version": "pilot-v1",
    "target_subjects": 12,
    "sessions_per_subject": 2,          # two separate days: test-retest of wearing/calibration
    "exercises": {
        "WALK": {"duration_s": 120, "notes": "self-selected speed, straight path"},
        "SQUAT": {"reps": 10, "notes": "bilateral, to comfortable depth"},
        "SIT_TO_STAND": {"reps": 10, "notes": "standard chair, arms crossed"},
        "STEP_UP": {"reps": 8, "notes": "8 per leading leg"},
        "KNEE_EXTENSION": {"reps": 10, "notes": "10 per side, seated"},
        "SINGLE_LEG_BALANCE": {"duration_s": 30, "notes": "30 s per side"},
    },
    # Activities for the activity model, recorded as labelled segments inside sessions.
    "activity_segments": ["sitting", "standing", "walking", "stairs_up", "stairs_down", "lying"],
    "per_session_requirements": [
        "MODEL_TRAINING consent recorded before the first session",
        "calibration completed (still + slow movement) at the start of every session",
        "validation verdict USABLE or USABLE_WITH_WARNINGS",
        "therapist labels: repetition index per side; phases on >= 3 reps per exercise; "
        "quality rating per repetition (docs/LABELLING_GUIDE.md)",
        "video recording (stored separately, under the same consent) to verify labels",
    ],
    "split": "leave-subjects-out; never split one subject's sessions across train and test",
}
