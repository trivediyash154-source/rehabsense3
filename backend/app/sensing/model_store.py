"""Process-wide cache of the configured activity model bundles.

Loaded lazily on first use. A missing or rejected bundle is not an error for
the pipeline: inference reports MODEL_UNAVAILABLE with the reason, and every
other stage (calibration, bilateral, force/motion, repetitions, MQI) keeps
working, because none of them depend on the activity model.
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.sensing.inference import BundleError, ModelBundle, find_bundle

logger = get_logger("rehabsense.models")

_lock = threading.Lock()
_cache: dict[str, tuple[ModelBundle | None, str | None]] = {}


def _root() -> Path:
    root = Path(get_settings().ml_model_dir)
    if not root.is_absolute():
        # Relative to the backend directory, regardless of the cwd.
        root = (Path(__file__).resolve().parents[2] / root).resolve()
    return root


def _load(name: str, version: str | None) -> tuple[ModelBundle | None, str | None]:
    path = find_bundle(_root(), name, version)
    if path is None:
        return None, f"no bundle named {name!r} under {_root()}"
    try:
        bundle = ModelBundle.load(path)
    except (BundleError, OSError, ValueError) as exc:
        log_event(logger, "model_rejected", name=name, path=str(path), reason=str(exc))
        return None, str(exc)
    log_event(logger, "model_loaded", name=bundle.name, version=bundle.version)
    return bundle, None


# A deployment may switch a model off (e.g. ML_ACTIVITY_MODEL_SINGLE=none on a
# 512 MB host: the single-side forest alone needs ~440 MB in memory). That is
# a configuration of the deployment, not a change to the model: sessions then
# report MODEL_UNAVAILABLE with this reason, exactly as for a missing bundle.
DISABLED_VALUES = {"", "none", "off", "disabled"}


def disabled_reason(kind: str) -> str:
    var = "ML_ACTIVITY_MODEL" if kind == "bilateral" else "ML_ACTIVITY_MODEL_SINGLE"
    return f"{kind} activity model disabled on this deployment ({var}=none)"


def is_disabled(kind: str) -> bool:
    s = get_settings()
    name = s.ml_activity_model if kind == "bilateral" else s.ml_activity_model_single
    return (name or "").strip().lower() in DISABLED_VALUES


def get(kind: str) -> tuple[ModelBundle | None, str | None]:
    """kind: 'bilateral' or 'single_side'. Returns (bundle, reason_if_none)."""
    if is_disabled(kind):
        return None, disabled_reason(kind)
    s = get_settings()
    name, version = (
        (s.ml_activity_model, s.ml_activity_model_version) if kind == "bilateral"
        else (s.ml_activity_model_single, s.ml_activity_model_single_version)
    )
    key = f"{name}:{version}"
    with _lock:
        if key not in _cache:
            _cache[key] = _load(name, version)
        return _cache[key]


def status() -> dict:
    out = {}
    for kind in ("bilateral", "single_side"):
        if is_disabled(kind):
            out[kind] = {"loaded": False, "disabled": True, "reason": disabled_reason(kind)}
            continue
        bundle, reason = get(kind)
        out[kind] = bundle.summary() if bundle else {"loaded": False, "reason": reason}
    return out


def reset() -> None:
    with _lock:
        _cache.clear()
