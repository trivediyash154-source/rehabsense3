"""Notifications addressed to the authenticated user."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbDep
from app.core.exceptions import NotFound
from app.db.models.notification import Notification
from app.db.models.base import utc_iso

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    user: CurrentUser, db: DbDep,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Notification).where(Notification.recipient_id == user.id)
    count_stmt = select(func.count(Notification.id)).where(Notification.recipient_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
        count_stmt = count_stmt.where(Notification.read_at.is_(None))

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()

    return {
        "items": [
            {
                "id": n.id, "type": n.type.value, "severity": n.severity.value,
                "title": n.title, "message": n.message,
                "created_at": utc_iso(n.created_at),
                "read_at": utc_iso(n.read_at),
                "related_patient_id": n.related_patient_id,
                "related_session_id": n.related_session_id,
                "related_report_id": n.related_report_id,
            }
            for n in rows
        ],
        "total": total,
        "unread": db.execute(
            select(func.count(Notification.id)).where(
                Notification.recipient_id == user.id, Notification.read_at.is_(None)
            )
        ).scalar_one(),
        "limit": limit,
        "offset": offset,
    }


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(notification_id: int, user: CurrentUser, db: DbDep) -> None:
    note = db.get(Notification, notification_id)
    # Another user's notification is reported as missing, not forbidden.
    if note is None or note.recipient_id != user.id:
        raise NotFound("Notification not found.")
    if note.read_at is None:
        note.read_at = datetime.now(timezone.utc)
        db.commit()
