"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    dev,
    focus,
    auth,
    devices,
    exercises,
    hardware,
    health,
    notifications,
    patients,
    progress,
    realtime,
    reports,
    sessions,
    users,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger, log_event
from app.db.database import Base, SessionLocal, engine
from app.db.seed import seed_exercises

# Codes for errors raised by the framework itself (a 404 on an unknown path,
# a 405, and so on) rather than by our own typed exceptions.
_CODE_BY_STATUS = {
    401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger("rehabsense.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.assert_production_safe()
    # Alembic owns the schema; create_all only bootstraps a fresh dev SQLite
    # file so `uvicorn app.main:app` works with zero setup, as documented.
    if settings.database_url.startswith("sqlite") and not settings.is_production:
        Base.metadata.create_all(bind=engine)
    if settings.require_migrated_schema:
        from app.api.health import schema_status

        db = SessionLocal()
        try:
            if schema_status(db) != "ok":
                raise RuntimeError("Database schema is not at the Alembic head. "
                                   "Run `alembic upgrade head` before starting the API.")
        finally:
            db.close()
    db = SessionLocal()
    try:
        created = seed_exercises(db)
    finally:
        db.close()
    log_event(logger, "startup", analytics_version=settings.analytics_version,
              exercises_seeded=created, debug=settings.debug)
    yield
    # No simulator process may outlive the server that started it.
    from app.services import sim_runner

    sim_runner.stop_all()
    log_event(logger, "shutdown")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "RehabSense backend. Every ROM and recovery figure returned by this API is an "
        "estimated decision-support indicator, not a diagnosis or clinical measurement."
    ),
    lifespan=lifespan,
)

# Explicit origins only — never a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """Reject oversized bodies before they are read (JSON APIs only need ~KB)."""
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > settings.max_request_bytes:
        return JSONResponse(status_code=413, content={"code": "PAYLOAD_TOO_LARGE",
                                                      "message": "Request body too large."})
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    """Flatten every HTTP error to one shape: {code, message, ...context}.

    FastAPI nests `HTTPException.detail` under a "detail" key, which makes a
    client dig two levels for the code. Errors are part of the API contract, so
    they get the same flat, documented shape as any successful response.
    """
    detail = exc.detail
    if isinstance(detail, dict):
        content = dict(detail)
        content.setdefault("code", "ERROR")
        content.setdefault("message", "")
    else:
        content = {"code": _CODE_BY_STATUS.get(exc.status_code, "ERROR"), "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=content,
                        headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Give request-validation failures the same shape as every other error."""
    fields = [
        {"field": ".".join(str(p) for p in err.get("loc", [])[1:]), "message": err.get("msg", "")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "The request body failed validation.",
            "fields": fields,
        },
    )


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Never leak an internal exception to a client."""
    logger.exception("unhandled error", extra={"context": {"path": request.url.path}})
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "Something went wrong."},
    )


API = settings.api_prefix

# Documented contract lives at /api/... ; /api/v1/... is an alias so clients
# can migrate to a versioned path without a breaking change.
for prefix in (API, f"{API}/v1"):
    app.include_router(health.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(patients.router, prefix=prefix)
    app.include_router(progress.router, prefix=prefix)
    app.include_router(sessions.router, prefix=prefix)
    app.include_router(reports.router, prefix=prefix)
    app.include_router(devices.router, prefix=prefix)
    app.include_router(exercises.router, prefix=prefix)
    app.include_router(focus.router, prefix=prefix)
    app.include_router(dev.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(hardware.router, prefix=prefix)

# WebSockets are unprefixed, exactly as the hardware contract specifies.
app.include_router(realtime.router)


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "analytics_version": settings.analytics_version,
        "docs": "/docs",
        "responsible_use": (
            "Research prototype. Estimated decision-support indicators only."
        ),
    }
