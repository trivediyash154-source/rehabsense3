"""Seed the exercise catalogue.

Reference data only — no patients, sessions or metrics are invented here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.db.models.exercise import Exercise, MovementType
from app.db.models.session import ExerciseType

CATALOGUE = [
    {
        "key": ExerciseType.WALK, "name": "Walking", "category": "Gait symmetry · cadence",
        "movement_type": MovementType.GAIT,
        "description": "Level walking is the reference movement for bilateral comparison. Both limbs complete the same cycle, so timing differences between them become measurable.",
        "supported_metrics": ["rom", "cadence", "symmetry", "stance_time"],
        "phases": ["Heel strike", "Stance", "Toe off", "Swing"],
        "cue": "Walk at a comfortable pace. The system compares the two limbs against each other, not against a target.",
    },
    {
        "key": ExerciseType.SQUAT, "name": "Squat", "category": "Range of motion · loading",
        "movement_type": MovementType.REPETITION,
        "description": "A controlled bilateral descent. Knee flexion is estimated from the thigh-shin relationship on each side independently.",
        "supported_metrics": ["rom", "symmetry", "repetition_quality"],
        "phases": ["Descent", "Bottom", "Ascent", "Reset"],
        "cue": "Descend only as far as is comfortable. Depth is recorded, not scored against a target.",
    },
    {
        "key": ExerciseType.SIT_TO_STAND, "name": "Sit to stand", "category": "Repetition quality",
        "movement_type": MovementType.REPETITION,
        "description": "A repeated functional movement with clear start and end positions, which makes repetition segmentation straightforward.",
        "supported_metrics": ["rom", "repetition_quality", "symmetry"],
        "phases": ["Lean", "Lift off", "Extend", "Sit"],
        "cue": "Rise without pushing through the arms where possible.",
    },
    {
        "key": ExerciseType.STEP_UP, "name": "Step up", "category": "Single-limb loading",
        "movement_type": MovementType.REPETITION,
        "description": "Loads one limb at a time, which surfaces asymmetry that bilateral movements can mask.",
        "supported_metrics": ["rom", "repetition_quality", "symmetry"],
        "phases": ["Plant", "Drive", "Stand", "Lower"],
        "cue": "Lead with the same limb throughout so the comparison stays consistent.",
    },
    {
        "key": ExerciseType.SINGLE_LEG_BALANCE, "name": "Single-leg balance",
        "category": "Stability · control", "movement_type": MovementType.HOLD,
        "description": "A quasi-static hold. Small angular corrections are visible in the signal as continuous micro-movement.",
        "supported_metrics": ["steadiness"],
        "phases": ["Lift", "Hold", "Correct", "Lower"],
        "cue": "Hold as steadily as possible. Small corrections are expected and are part of the signal.",
    },
    {
        "key": ExerciseType.KNEE_EXTENSION, "name": "Seated knee extension",
        "category": "Isolated range", "movement_type": MovementType.REPETITION,
        "description": "Seated extension isolates the knee, so the estimate depends less on hip and trunk motion than standing movements do.",
        "supported_metrics": ["rom", "repetition_quality"],
        "phases": ["Extend", "Hold", "Lower", "Rest"],
        "cue": "Extend smoothly and lower under control.",
    },
]


def seed_exercises(db: DbSession) -> int:
    """Insert missing catalogue rows. Safe to run from several API instances
    starting at once (serverless cold starts): if another instance inserted
    the same rows first, the unique key rejects ours and that is success."""
    created = 0
    for entry in CATALOGUE:
        existing = db.execute(
            select(Exercise).where(Exercise.key == entry["key"])
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(Exercise(**entry))
        created += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return 0
    return created
