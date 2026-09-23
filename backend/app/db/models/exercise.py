"""Exercise catalogue and clinician-authored plans.

The catalogue is served to the frontend so exercises are not hardcoded there
forever. Plans are clinician-authored only — the system never generates a
prescription on its own.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TimestampMixin
from app.db.models.session import ExerciseType

if TYPE_CHECKING:
    pass


class MovementType(str, enum.Enum):
    GAIT = "GAIT"
    REPETITION = "REPETITION"
    HOLD = "HOLD"


class Exercise(Base, TimestampMixin):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[ExerciseType] = mapped_column(Enum(ExerciseType), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(Enum(MovementType), nullable=False)
    # Which metrics this movement can legitimately produce; the analytics
    # engine will not report cadence for a seated exercise, for example.
    supported_metrics: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    phases: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    cue: Mapped[str | None] = mapped_column(Text)
    demo_asset: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ExercisePlan(Base, TimestampMixin):
    __tablename__ = "exercise_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Always a real clinician. Nothing auto-generates a plan.
    authored_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PlanStatus] = mapped_column(Enum(PlanStatus), default=PlanStatus.DRAFT, nullable=False)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["ExercisePlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class ExercisePlanItem(Base):
    __tablename__ = "exercise_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False)
    target_reps: Mapped[int | None] = mapped_column()
    target_sessions_per_week: Mapped[int | None] = mapped_column()
    target_rom_deg: Mapped[float | None] = mapped_column()
    clinician_note: Mapped[str | None] = mapped_column(Text)

    plan: Mapped["ExercisePlan"] = relationship(back_populates="items")
    exercise: Mapped["Exercise"] = relationship()
