"""Sign-in identities, kept separate from the RehabSense user they belong to.

A `User` is the person's RehabSense account: role, profile and records. A
`UserIdentity` is one external way of proving to be that person -- a Google
account or a Facebook account -- keyed by the provider's own stable subject
identifier, never by an email address (emails change hands and are not proof
of anything on their own). One user may hold several identities, at most one
per provider.

The password method is the `users.password_hash` column (email is its login
identifier), so it needs no row here. "phone" is reserved for an SMS method,
which is not configured.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TimestampMixin
from app.db.models.user import User

EXTERNAL_PROVIDERS = ("google", "facebook", "phone")


class UserIdentity(Base, TimestampMixin):
    __tablename__ = "user_identities"
    __table_args__ = (
        # The identity key: the provider's subject, unique per provider.
        UniqueConstraint("provider", "provider_subject", name="uq_identity_provider_subject"),
        # One Google (or Facebook) account per RehabSense user.
        UniqueConstraint("user_id", "provider", name="uq_identity_user_provider"),
        CheckConstraint("provider IN ('google', 'facebook', 'phone')", name="ck_identity_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True,
                                         nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    # Google: the ID token's `sub`. Facebook: the app-scoped user id.
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    # As last reported by the provider. Informational: never used to match.
    provider_email: Mapped[str | None] = mapped_column(String(254))
    provider_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class OAuthStateUse(Base):
    """Every OAuth `state` that has reached a callback, so none works twice.

    The state itself travels in a signed, short-lived HttpOnly cookie; this
    table is what makes it single-use across every API instance. Only a
    SHA-256 of the state is stored.
    """

    __tablename__ = "oauth_state_uses"

    id: Mapped[int] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
