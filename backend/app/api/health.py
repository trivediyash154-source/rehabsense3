"""Health and diagnostics.

`/api/health` keeps its documented shape. The sub-checks report status only
and never expose connection strings or internal configuration.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import CurrentUser, DbDep
from app.core.config import get_settings
from app.realtime.ws_manager import manager
from app.services.live_registry import registry

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness only. See /health/ready for dependencies."""
    return {"status": "ok"}


@lru_cache
def head_revision() -> str:
    """The Alembic head revision, read from the migration files as text.

    Importing Alembic's script machinery (it loads its autogenerate plugins and
    imports every migration module) ran on every serverless cold start just to
    learn one string. The files declare `revision` and
    `down_revision` literally, so the head is the revision nothing points
    back to. tests/test_deployment.py checks this against Alembic itself.
    """
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        down = re.search(r"^down_revision\s*=\s*(.+)$", text, re.M)
        if rev:
            revisions.add(rev.group(1))
        if down:
            parents.update(re.findall(r"['\"]([^'\"]+)['\"]", down.group(1)))
    heads = revisions - parents
    if len(heads) != 1:
        raise RuntimeError(f"Expected exactly one Alembic head, found {sorted(heads)}")
    return heads.pop()


def schema_status(db) -> str:
    """'ok' when the database is at the Alembic head, else 'migration_required'."""
    head = head_revision()
    try:
        current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        db.rollback()
        return "migration_required"
    return "ok" if current == head else "migration_required"


@router.get("/health/ready")
def health_ready(db: DbDep):
    """Readiness: each dependency reported as ok / degraded / error. No internals."""
    from app.sensing import model_store
    from app.services.storage import get_storage

    out = {"api": "ok"}
    try:
        db.execute(text("SELECT 1"))
        out["database"] = "ok"
        out["schema"] = schema_status(db)
    except Exception:
        out["database"], out["schema"] = "error", "unknown"
    try:
        st = model_store.status()
        # A model the deployment deliberately switched off is not a fault;
        # one that is configured but failed to load is.
        out["ml"] = "ok" if all(
            v.get("loaded", True) is not False or v.get("disabled") for v in st.values()
        ) else "degraded"
    except Exception:
        out["ml"] = "error"
    try:
        out["storage"] = "ok" if get_storage().health() else "error"
    except Exception:
        out["storage"] = "error"
    out["realtime"] = "ok"
    out["status"] = "ok" if all(v == "ok" for v in out.values()) else "degraded"
    # A load balancer / host health check reads the status code, not the body.
    return JSONResponse(out, status_code=200 if out["status"] == "ok" else 503)


@router.get("/health/database")
def health_database(db: DbDep):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "schema": schema_status(db)}
    except Exception:
        return {"status": "error"}


@router.get("/health/websocket")
def health_websocket(user: CurrentUser):
    """Counts only; which sessions are live is clinical metadata."""
    return {"status": "ok", "active_sessions": len(manager.active_sessions)}


@router.get("/health/analytics")
def health_analytics(user: CurrentUser):
    settings = get_settings()
    return {
        "status": "ok",
        "analytics_version": settings.analytics_version,
        "sample_rate_hz": settings.sample_rate_hz,
        "complementary_alpha": settings.complementary_alpha,
        "lowpass_cutoff_hz": settings.lowpass_cutoff_hz,
        "weights": settings.weights,
        "live_sessions": registry.status()["count"],
    }
