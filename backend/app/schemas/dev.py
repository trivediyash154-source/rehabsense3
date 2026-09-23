from __future__ import annotations

from pydantic import BaseModel, Field

from app.db.models.session import ExerciseType


class SeedRequest(BaseModel):
    """How much demo data to generate."""

    patients: int = Field(default=3, ge=1, le=5)
    exercise: ExerciseType = ExerciseType.WALK
    # Re-create records that already exist rather than reusing them.
    force: bool = False
    # Wall-clock speed-up while streaming. Sample timestamps, ordering and
    # count are unchanged, so a fast seed stores exactly what a real-time
    # run would -- it just does not take an hour to build a demo history.
    speed: float = Field(default=1.0, ge=1.0, le=60.0)
