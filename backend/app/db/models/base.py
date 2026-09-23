"""Shared column mixins."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def as_utc(value: datetime | None) -> datetime | None:
    """Normalise a stored datetime to timezone-aware UTC.

    SQLite has no native timezone type, so values written as aware come back
    naive. Comparing one of those to `datetime.now(timezone.utc)` raises
    TypeError, which is easy to miss until an expiry check runs in
    production. Everything read back from the database goes through here.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def utc_iso(value: datetime | None) -> str | None:
    """Serialise a stored datetime as an unambiguous UTC ISO-8601 string.

    Without this, SQLite's naive values serialise with no offset, and
    `Date.parse` in the browser reads them as *local* time -- shifting every
    session timestamp by the viewer's UTC offset. Emitting an explicit "Z"
    removes the ambiguity for every client.
    """
    aware = as_utc(value)
    if aware is None:
        return None
    # astimezone, not just a label: PostgreSQL returns genuinely aware values,
    # which may carry a non-UTC offset. Emitting those unconverted would put
    # two different offset conventions in one payload.
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
