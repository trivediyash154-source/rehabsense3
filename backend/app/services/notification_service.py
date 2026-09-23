"""Notification creation with de-duplication."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models.notification import Notification, NotificationSeverity, NotificationType


def notify(
    db: DbSession,
    *,
    recipient_id: int,
    type: NotificationType,
    title: str,
    message: str,
    severity: NotificationSeverity = NotificationSeverity.INFO,
    dedupe_key: str | None = None,
    **related,
) -> Notification | None:
    """Create a notification, or return None if an identical one exists.

    The dedupe key makes notification creation idempotent, so a retried
    operation cannot produce a duplicate alert.
    """
    if dedupe_key:
        existing = db.execute(
            select(Notification).where(Notification.dedupe_key == dedupe_key)
        ).scalar_one_or_none()
        if existing:
            return None

    note = Notification(
        recipient_id=recipient_id, type=type, title=title, message=message,
        severity=severity, dedupe_key=dedupe_key,
        related_patient_id=related.get("patient_id"),
        related_session_id=related.get("session_id"),
        related_report_id=related.get("report_id"),
    )
    db.add(note)
    db.flush()
    return note
