"""Notifications addressed to a specific user."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.base import TimestampMixin


class NotificationType(str, enum.Enum):
    SESSION_COMPLETED = "SESSION_COMPLETED"
    REPORT_READY = "REPORT_READY"
    DEVICE_CONNECTED = "DEVICE_CONNECTED"
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    SIGNAL_QUALITY_LOW = "SIGNAL_QUALITY_LOW"
    NEW_RISK_FLAG = "NEW_RISK_FLAG"
    REVIEW_RECOMMENDED = "REVIEW_RECOMMENDED"
    PROGRESS_MILESTONE = "PROGRESS_MILESTONE"
    EXERCISE_PLAN_UPDATED = "EXERCISE_PLAN_UPDATED"


class NotificationSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType), nullable=False)
    severity: Mapped[NotificationSeverity] = mapped_column(
        Enum(NotificationSeverity), default=NotificationSeverity.INFO, nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    related_patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    related_session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    related_report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"))

    # Prevents duplicate notifications when an operation is retried.
    dedupe_key: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
