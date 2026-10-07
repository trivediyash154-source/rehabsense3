"""Patient profiles and the clinician relationship."""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.session import Session
    from app.db.models.user import User


class Leg(str, enum.Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class PatientProfile(Base, TimestampMixin):
    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("demo_key", name="uq_patients_demo_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Optional: a patient record can exist before the person has a login.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(120))
    age: Mapped[int | None] = mapped_column()
    sex: Mapped[str | None] = mapped_column(String(16))
    operated_leg: Mapped[Leg] = mapped_column(Enum(Leg), nullable=False)
    surgery_date: Mapped[date | None] = mapped_column(Date)
    recovery_start: Mapped[date | None] = mapped_column(Date)
    clinic_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # Clinician-only. Never serialised into a patient-facing response.
    notes: Mapped[str | None] = mapped_column(Text)
    # Rehabilitation programme, as a clinician would set it.
    program: Mapped[str | None] = mapped_column(String(80))
    program_days: Mapped[int | None] = mapped_column()
    planned_sessions: Mapped[int | None] = mapped_column()
    # Where this record came from. NULL: entered for a real person. Otherwise
    # SYNTHETIC_DEMONSTRATION or PUBLIC_DATASET_REPLAY (app/sensing/provenance.py)
    # -- a fictional or dataset record that must never be presented as a patient.
    provenance: Mapped[str | None] = mapped_column(String(24), index=True)
    # Stable key of a generated record ("synthetic-demo/v1/P01"), so the seed is
    # idempotent and --reset-demo can only ever touch what it created.
    demo_key: Mapped[str | None] = mapped_column(String(64))

    user: Mapped["User | None"] = relationship(
        back_populates="patient_profile", foreign_keys=[user_id]
    )
    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="patient", cascade="all, delete-orphan"
    )
    assignments: Mapped[list["PatientAssignment"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )


class AssignmentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class PatientAssignment(Base, TimestampMixin):
    """Which clinician is responsible for which patient.

    Authorisation for a physiotherapist is derived from an ACTIVE row here —
    not from a role claim alone.
    """

    __tablename__ = "patient_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    clinician_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus), default=AssignmentStatus.ACTIVE, nullable=False
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient: Mapped["PatientProfile"] = relationship(back_populates="assignments")
