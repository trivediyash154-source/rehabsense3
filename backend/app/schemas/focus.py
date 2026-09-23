from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.db.models.session import ExerciseType
from app.schemas.types import UtcDatetime

# Bounds mirror focus_service so the API refuses nonsense before it reaches
# the database, with a message that says what is allowed.
MIN_TARGET_S = 60
MAX_TARGET_S = 6 * 3600


class FocusCreate(BaseModel):
    patient_id: int
    target_duration_s: int = Field(ge=MIN_TARGET_S, le=MAX_TARGET_S)
    exercise_type: ExerciseType = ExerciseType.WALK
    # The patient's own calendar day, so "today" matches their clock.
    local_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    scheduled_for: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


class FocusUpdate(BaseModel):
    target_duration_s: int | None = Field(default=None, ge=MIN_TARGET_S, le=MAX_TARGET_S)
    exercise_type: ExerciseType | None = None
    scheduled_for: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ReminderCreate(BaseModel):
    patient_id: int
    time_of_day: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    timezone_name: str = Field(default="UTC", max_length=64)
    target_duration_s: int = Field(default=1800, ge=MIN_TARGET_S, le=MAX_TARGET_S)
    exercise_type: ExerciseType = ExerciseType.WALK
    enabled: bool = True

    @field_validator("weekdays")
    @classmethod
    def _valid_days(cls, value: list[int]) -> list[int]:
        cleaned = sorted({int(d) for d in value})
        if not cleaned or any(d < 0 or d > 6 for d in cleaned):
            raise ValueError("weekdays must be 0 (Monday) to 6 (Sunday), and not empty.")
        return cleaned


class ReminderUpdate(BaseModel):
    time_of_day: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[int] | None = None
    timezone_name: str | None = Field(default=None, max_length=64)
    target_duration_s: int | None = Field(default=None, ge=MIN_TARGET_S, le=MAX_TARGET_S)
    exercise_type: ExerciseType | None = None
    enabled: bool | None = None

    @field_validator("weekdays")
    @classmethod
    def _valid_days(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        cleaned = sorted({int(d) for d in value})
        if not cleaned or any(d < 0 or d > 6 for d in cleaned):
            raise ValueError("weekdays must be 0 (Monday) to 6 (Sunday), and not empty.")
        return cleaned


class FocusSessionLink(BaseModel):
    """Attach a rehabilitation session to a focus block."""

    session_id: int


__all__ = [
    "FocusCreate", "FocusUpdate", "ReminderCreate", "ReminderUpdate",
    "FocusSessionLink", "UtcDatetime",
]
