from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.patient import Leg
from app.schemas.types import UtcDatetime


class PatientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    age: int | None = Field(default=None, ge=0, le=130)
    sex: str | None = Field(default=None, max_length=16)
    operated_leg: Leg
    surgery_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    user_id: int | None = None


class PatientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    preferred_name: str | None = Field(default=None, max_length=120)
    age: int | None = Field(default=None, ge=0, le=130)
    surgery_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class PatientPublic(BaseModel):
    """Patient-safe view. Clinician notes are deliberately absent."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    preferred_name: str | None = None
    age: int | None = None
    sex: str | None = None
    operated_leg: Leg
    surgery_date: date | None = None
    created_at: UtcDatetime


class PatientClinical(PatientPublic):
    """Adds the clinician-only fields. Only ever returned to a clinician."""

    notes: str | None = None
    clinic_id: str | None = None
    user_id: int | None = None
