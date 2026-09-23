"""Shared field types for API schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def _utc(value: datetime | None) -> str | None:
    """Serialise as UTC ISO-8601 with an explicit 'Z'.

    SQLite returns naive datetimes even for timezone-aware columns. Serialised
    as-is they carry no offset, and `Date.parse` in a browser reads a bare
    date-time as *local*, shifting every timestamp by the viewer's UTC offset.
    Being explicit removes the ambiguity for every client.
    """
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[datetime, PlainSerializer(_utc, return_type=str, when_used="json")]
