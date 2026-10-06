"""Dataset loaders. Every loader converts to RehabSense units (g, deg/s).

Each returns *recordings*: contiguous stretches of one activity by one
subject. Windows are cut inside a recording only, and every split is by
subject, so no window ever shares a subject (or a recording) across the
train/test boundary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

G = 9.80665
RAD2DEG = 180.0 / np.pi


@dataclass
class Recording:
    subject: str
    label: str
    source_activity: str
    rate_hz: float
    # Raw IMU blocks, (n, 6): ax ay az [g], gx gy gz [deg/s]. `right` is None
    # for single-IMU datasets: it is never synthesised from `left`.
    left: np.ndarray
    right: np.ndarray | None = None
    meta: dict = field(default_factory=dict)
    # Neutral gravity direction per sensor, from this subject's reserved
    # calibration recording (emulating the device's calibration step).
    neutral_left: np.ndarray | None = None
    neutral_right: np.ndarray | None = None


def unit(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-9)


def file_sha256(path: Path, limit_bytes: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        read = 0
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            read += len(chunk)
            if limit_bytes and read >= limit_bytes:
                break
    return h.hexdigest()
