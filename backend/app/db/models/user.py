"""Users and roles.

The PRD scoped auth to Phase 2; this implements it properly rather than
leaving a role flag the frontend could simply assert.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.patient import PatientProfile


class Role(str, enum.Enum):
    PATIENT = "PATIENT"
    PHYSIOTHERAPIST = "PHYSIOTHERAPIST"
    TECHNICIAN = "TECHNICIAN"
    ADMIN = "ADMIN"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    # Argon2id digest. The plaintext is never stored or logged. NULL for an
    # account created through Google or Facebook that never set a password:
    # password sign-in is then refused like any wrong password.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.PATIENT, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    preferences: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Bumped on password change / logout-everywhere; older tokens stop validating.
    token_version: Mapped[int] = mapped_column(default=0, nullable=False)

    # Failed-login handling. Counted server-side so a client cannot reset it by
    # reloading, and cleared on the first success.
    failed_login_count: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient_profile: Mapped["PatientProfile | None"] = relationship(
        back_populates="user", uselist=False, foreign_keys="PatientProfile.user_id"
    )

    @property
    def display_name(self) -> str:
        return self.preferred_name or self.name

    def is_locked(self, now: datetime) -> bool:
        """True while a lockout window from repeated failures is still open."""
        if self.locked_until is None:
            return False
        locked_until = self.locked_until
        # SQLite hands back naive datetimes; compare in UTC either way.
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        return locked_until > now
