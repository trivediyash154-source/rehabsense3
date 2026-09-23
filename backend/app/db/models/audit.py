"""Audit trail for actions that touch health-related data."""

from __future__ import annotations

import enum

from sqlalchemy import Enum, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.base import TimestampMixin


class AuditAction(str, enum.Enum):
    USER_REGISTERED = "USER_REGISTERED"
    USER_LOGIN = "USER_LOGIN"
    USER_LOGIN_FAILED = "USER_LOGIN_FAILED"
    USER_LOGIN_BLOCKED = "USER_LOGIN_BLOCKED"
    USER_LOGOUT = "USER_LOGOUT"
    PATIENT_ASSIGNED = "PATIENT_ASSIGNED"
    PATIENT_CREATED = "PATIENT_CREATED"
    PATIENT_UPDATED = "PATIENT_UPDATED"
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_ENDED = "SESSION_ENDED"
    SESSION_CANCELLED = "SESSION_CANCELLED"
    DEVICE_CONNECTED = "DEVICE_CONNECTED"
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    REPORT_GENERATED = "REPORT_GENERATED"
    REPORT_SHARED = "REPORT_SHARED"
    REPORT_SHARE_REVOKED = "REPORT_SHARE_REVOKED"
    NOTE_UPDATED = "NOTE_UPDATED"
    RISK_FLAG_ACKNOWLEDGED = "RISK_FLAG_ACKNOWLEDGED"
    PLAN_PUBLISHED = "PLAN_PUBLISHED"


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[AuditAction] = mapped_column(Enum(AuditAction), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(40), index=True)
    # Identifiers and outcomes only — never note bodies or credentials.
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
