"""Mounting-independent 1-DoF tilt for one IMU.

v1 assumed every IMU was strapped with its y axis on the flexion axis
(`atan2(ax, az)`, `gy`). Two MPU6050s strapped by hand onto two legs will not
share an orientation, and neither will match a public dataset's sensor frame.
So the frame is *measured* instead of assumed:

  g0  neutral gravity direction in the sensor frame, from the still phase of
      calibration (calibration step 7)
  u   principal rotation axis in the sensor frame, from the dominant gyro
      direction during the calibration movement (step 8); if no calibration
      movement was captured, from the stream itself once it moves

Tilt is the rotation about `u` away from the neutral pose:

  theta_acc  = -signed angle from g0 to a, both projected onto the plane
               normal to u (gravity rotates opposite to the sensor)
  theta      = alpha * (theta + (w . u) * dt) + (1 - alpha) * theta_acc

This is a *segment tilt*, not a joint angle. With one IMU per leg there is no
second segment to subtract, so no knee angle is reported. Its range over a
repetition is reported as a "range-of-motion proxy" and named that way.

If u is close to g0 (rotation about the vertical), gravity carries no
information about the tilt and `observable` is False: the estimate is then
gyro-only with a slow leak, and consumers are told.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.processing.filters import butterworth_lowpass


def unit(v: np.ndarray) -> np.ndarray | None:
    n = float(np.linalg.norm(v))
    return None if n < 1e-9 or not math.isfinite(n) else v / n


def principal_axis(gyro: np.ndarray, min_rms_dps: float = 6.0) -> np.ndarray | None:
    """Dominant rotation axis of a gyro block (n x 3, deg/s), or None if still.

    First principal component of the angular-velocity vectors: during a
    flexion/extension movement almost all rotation is about one axis.
    """
    g = gyro[~np.isnan(gyro).any(axis=1)]
    if len(g) < 20:
        return None
    rms = float(np.sqrt(np.mean(np.sum(g * g, axis=1))))
    if rms < min_rms_dps:
        return None
    _, _, vt = np.linalg.svd(g - 0.0, full_matrices=False)
    axis = vt[0]
    # Sign is arbitrary from SVD; fix it so positive rotation is the
    # direction the segment moved first, which is stable across sessions.
    proj = np.abs(np.einsum("ij,j->i", g, axis))
    first = g[np.argmax(proj > 0.5 * proj.max())]
    if float(first @ axis) < 0:
        axis = -axis
    return axis


@dataclass
class TiltEstimator:
    sample_rate_hz: float
    alpha: float = 0.98
    cutoff_hz: float = 5.0
    g0: np.ndarray | None = None
    axis: np.ndarray | None = None

    theta: float = 0.0
    observable: bool = False
    _lp: list = field(default_factory=list, init=False)
    _started: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._lp = [butterworth_lowpass(self.cutoff_hz, self.sample_rate_hz) for _ in range(3)]
        self._refresh_observable()

    def configure(self, g0: np.ndarray | None, axis: np.ndarray | None) -> None:
        if g0 is not None:
            self.g0 = unit(np.asarray(g0, dtype=float))
        if axis is not None:
            self.axis = unit(np.asarray(axis, dtype=float))
        self._refresh_observable()

    def _refresh_observable(self) -> None:
        if self.g0 is None or self.axis is None:
            self.observable = False
            return
        # Component of gravity perpendicular to the axis.
        perp = self.g0 - (self.g0 @ self.axis) * self.axis
        self.observable = float(np.linalg.norm(perp)) > 0.3

    @property
    def ready(self) -> bool:
        return self.g0 is not None and self.axis is not None

    def _acc_angle(self, acc: np.ndarray) -> float | None:
        u, g0 = self.axis, self.g0
        a_p = acc - (acc @ u) * u
        g_p = g0 - (g0 @ u) * u
        if np.linalg.norm(a_p) < 1e-6 or np.linalg.norm(g_p) < 1e-6:
            return None
        cross = np.cross(g_p, a_p)
        ang = math.degrees(math.atan2(float(cross @ u), float(g_p @ a_p)))
        return -ang

    def update(self, acc: np.ndarray, gyro: np.ndarray, dt: float) -> float | None:
        """One sample. acc in g, gyro in deg/s (bias already removed)."""
        if not self.ready or np.isnan(acc).any() or np.isnan(gyro).any():
            return None
        acc_f = np.array([f(float(x)) for f, x in zip(self._lp, acc)])
        w = float(gyro @ self.axis)
        theta_acc = self._acc_angle(acc_f) if self.observable else None
        if not self._started:
            self.theta = theta_acc if theta_acc is not None else 0.0
            self._started = True
            return self.theta
        dt = max(1e-4, min(dt, 0.5))
        predicted = self.theta + w * dt
        if theta_acc is None:
            # Gyro only: leak slowly toward neutral so drift stays bounded.
            self.theta = predicted * (1.0 - 0.02 * dt)
        else:
            self.theta = self.alpha * predicted + (1.0 - self.alpha) * theta_acc
        return self.theta
