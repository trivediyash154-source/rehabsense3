"""Canonical shapes for every live message.

The four documented message types keep their exact structure for backwards
compatibility; the additions are new types rather than changes to existing
ones, so an older client keeps working.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any


def _envelope(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    # Explicit "Z" so a browser cannot read the event time as local.
    return {
        "type": kind,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **payload,
    }


# --- documented contract (unchanged shape) ------------------------------- #

def connection_status(payload: dict) -> dict:
    return _envelope("connection_status", payload)


def metric_update(payload: dict) -> dict:
    return _envelope("metric_update", payload)


def rep_event(payload: dict) -> dict:
    return _envelope("rep_event", payload)


def risk_flag(payload: dict) -> dict:
    return _envelope("risk_flag", payload)


# --- additions ----------------------------------------------------------- #

def calibration_status(payload: dict) -> dict:
    return _envelope("calibration_status", payload)


def device_status(payload: dict) -> dict:
    return _envelope("device_status", payload)


def session_status(payload: dict) -> dict:
    return _envelope("session_status", payload)


def signal_quality(payload: dict) -> dict:
    return _envelope("signal_quality", payload)


def report_ready(payload: dict) -> dict:
    return _envelope("report_ready", payload)


def heartbeat() -> dict:
    return {"type": "heartbeat", "ts": time.time()}


def from_processor_event(event) -> dict:
    """Map a SessionProcessor event onto its wire message.

    `seq` travels with the event so a client can ignore a snapshot that
    arrives after a newer one.
    """
    message = _envelope(event.type, event.payload)
    message["seq"] = getattr(event, "seq", 0)
    return message
