"""Recovery Focus: a planned rehabilitation block and its adherence record.

Focus is deliberately a *wrapper* around the existing `Session`, not a second
session system. A focus block owns the plan (how long the patient intended to
work) and the clock (when they actually did, minus pauses). Everything about
the movement itself -- repetitions, ROM, symmetry, confidence -- stays on the
`Session` rows linked to the block, so there is exactly one source of truth
for a number and Focus can never disagree with the session it summarises.

All timing is derived from the `FocusEvent` ledger rather than stored as a
running counter. A ledger of timestamps survives a browser refresh, a
navigation, a backend restart and a clock that was never ticking while the
tab was in the background -- none of which a decrementing counter survives.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TimestampMixin
from app.db.models.session import ExerciseType

if TYPE_CHECKING:
    from app.db.models.patient import PatientProfile
    from app.db.models.session import Session


class FocusStatus(str, enum.Enum):
    """Lifecycle of a planned block.

    READY exists before the patient starts, so a plan made in advance (or by
    a reminder) is a real record rather than an implicit absence.
    INTERRUPTED marks a block that was never closed properly -- the tab was
    shut, the machine slept -- which must not be silently counted as
    completed adherence.
    """

    READY = "READY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class FocusEventKind(str, enum.Enum):
    STARTED = "STARTED"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class FocusSession(Base, TimestampMixin):
    __tablename__ = "focus_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    # The plan.
    target_duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    exercise_type: Mapped[ExerciseType] = mapped_column(Enum(ExerciseType), nullable=False)
    # Local wall-clock date the block belongs to, so "today" and the calendar
    # agree with the patient's own day rather than with UTC.
    local_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[FocusStatus] = mapped_column(
        Enum(FocusStatus), default=FocusStatus.READY, nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    patient: Mapped["PatientProfile"] = relationship()
    events: Mapped[list["FocusEvent"]] = relationship(
        back_populates="focus", cascade="all, delete-orphan", order_by="FocusEvent.at"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="focus", order_by="Session.started_at"
    )


class FocusEvent(Base):
    """One transition in a block's life. Timing is computed from these."""

    __tablename__ = "focus_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    focus_id: Mapped[int] = mapped_column(
        ForeignKey("focus_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[FocusEventKind] = mapped_column(Enum(FocusEventKind), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    focus: Mapped["FocusSession"] = relationship(back_populates="events")


class FocusReminder(Base, TimestampMixin):
    """A patient's intent to be reminded.

    This stores configuration only. Nothing here delivers anything: there is
    no push infrastructure in this deployment, so the API reports the next
    scheduled occurrence and the UI surfaces it, but no delivery event is
    ever fabricated.
    """

    __tablename__ = "focus_reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    # "18:30" in the patient's own timezone.
    time_of_day: Mapped[str] = mapped_column(String(5), nullable=False)
    # Monday=0 .. Sunday=6, stored as a sorted comma list, e.g. "0,1,2,3,4".
    weekdays: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4,5,6", nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    target_duration_s: Mapped[int] = mapped_column(Integer, default=1800, nullable=False)
    exercise_type: Mapped[ExerciseType] = mapped_column(
        Enum(ExerciseType), default=ExerciseType.WALK, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def weekday_list(self) -> list[int]:
        out: list[int] = []
        for part in (self.weekdays or "").split(","):
            part = part.strip()
            if part.isdigit() and 0 <= int(part) <= 6:
                out.append(int(part))
        return sorted(set(out))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
