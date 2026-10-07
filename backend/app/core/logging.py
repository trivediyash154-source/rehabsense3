"""Structured logging.

Log lines carry session/device context so a live session can be traced, but
never patient names, emails or note contents.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in getattr(record, "context", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log duplicates our structured lines.
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs every request URL at INFO. Calls to Google and Facebook carry
    # authorization codes, provider tokens and (for Facebook's debug_token)
    # the app secret in their query strings, so those lines must never print.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, message: str, **context: Any) -> None:
    """Log with structured context. Callers must pass only non-sensitive keys."""
    logger.info(message, extra={"context": context})
