"""Health and diagnostics.

`/api/health` keeps its documented shape. The sub-checks report status only
and never expose connection strings or internal configuration.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbDep
from app.core.config import get_settings
from app.realtime.ws_manager import manager
from app.services.live_registry import registry

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/database")
def health_database(db: DbDep):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "engine": get_settings().database_url.split("://", 1)[0]}
    except Exception:
        return {"status": "error"}


@router.get("/health/websocket")
def health_websocket():
    return {
        "status": "ok",
        "active_sessions": manager.active_sessions,
        "subscribers": {sid: manager.subscriber_count(sid) for sid in manager.active_sessions},
    }


@router.get("/health/analytics")
def health_analytics():
    settings = get_settings()
    return {
        "status": "ok",
        "analytics_version": settings.analytics_version,
        "sample_rate_hz": settings.sample_rate_hz,
        "complementary_alpha": settings.complementary_alpha,
        "lowpass_cutoff_hz": settings.lowpass_cutoff_hz,
        "weights": settings.weights,
        "live": registry.status(),
    }
