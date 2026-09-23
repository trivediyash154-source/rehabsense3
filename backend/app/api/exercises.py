"""Exercise catalogue, served from the database rather than hardcoded."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from app.db.models.exercise import Exercise

router = APIRouter(prefix="/exercises", tags=["exercises"])


@router.get("")
def list_exercises(user: CurrentUser, db: DbDep):
    rows = db.execute(select(Exercise).where(Exercise.active.is_(True)).order_by(Exercise.id)).scalars()
    return {
        "items": [
            {
                "id": e.id, "key": e.key.value, "name": e.name, "description": e.description,
                "category": e.category, "movement_type": e.movement_type.value,
                "supported_metrics": e.supported_metrics, "phases": e.phases,
                "cue": e.cue, "demo_asset": e.demo_asset,
            }
            for e in rows
        ]
    }
