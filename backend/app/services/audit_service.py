"""Audit trail writer."""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app.db.models.audit import AuditAction, AuditLog


def record(
    db: DbSession,
    *,
    action: AuditAction,
    entity_type: str,
    entity_id: str | int | None = None,
    actor_id: int | None = None,
    **context,
) -> AuditLog:
    """Append an audit row.

    Callers pass identifiers and outcomes only — never note bodies, message
    contents or credentials.
    """
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        context=context,
    )
    db.add(entry)
    return entry
