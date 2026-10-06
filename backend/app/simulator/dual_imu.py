"""Synthetic dual-MPU6050 + force signals, for development and tests only.

SYNTHETIC DATA. It exists so the pipeline can be built and tested before the
hardware exists. It is never training data and never patient data: every
stream that uses it declares `simulated: true`, the backend labels the
session SIMULATED, and dataset export excludes simulated sessions.

The kinematics are physically consistent, which is what makes it useful for
testing rather than decoration:

  * each leg segment rotates by theta(t) about the body's medio-lateral axis
  * each IMU is strapped on with its own random mounting rotation, so the
    backend cannot rely on a sensor axis lining up with anything
  * the accelerometer measures specific force: gravity plus tangential and
    centripetal acceleration of a point 0.2 m from the joint, rotated into
    the sensor frame; the gyroscope measures theta_dot in the sensor frame
  * per-sensor bias, white noise and MPU6050 quantisation are added
  * force channels model an FSR402 on a divider: monotonic, saturating,
    normalised ADC (`adc_norm`), not newtons
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

G = 9.80665
ACC_LSB_G = 1.0 / 8192.0      # +-4 g full scale
GYRO_LSB_DPS = 1.0 / 65.5     # +-500 deg/s full scale
LEVER_M = 0.2

# Segment (shank) tilt profiles: peak excursion (deg), period (s), shape.
PROFILES = {
    "SQUAT": {"amp": 35.0, "period": 3.0, "pattern": "sync"},
    "SIT_TO_STAND": {"amp": 22.0, "period": 3.6, "pattern": "sync"},
    "WALK": {"amp": 32.0, "period": 1.1, "pattern": "alternate"},
    "STEP_UP": {"amp": 40.0, "period": 2.6, "pattern": "unilateral"},
    "KNEE_EXTENSION": {"amp": 65.0, "period": 3.2, "pattern": "unilateral"},
    "SINGLE_LEG_BALANCE": {"amp": 3.0, "period": 4.0, "pattern": "sway"},
}


def rot_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def random_rotation(rng: np.random.Generator) -> np.ndarray:
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


@dataclass
class SideConfig:
    severity: float = 0.0        # 0 = unaffected; reduces range and speed
    delay_s: float = 0.0         # extra timing lag
    present: bool = True
    noise_scale: float = 1.0


@dataclass
class DualImuModel:
    exercise: str = "SQUAT"
    rate_hz: float = 100.0
    seed: int = 42
    left: SideConfig = field(default_factory=SideConfig)
    right: SideConfig = field(default_factory=SideConfig)
    force_sides: tuple = ("LEFT", "RIGHT")
    # Health check (1 s) + detected still period (3 s) + margin.
    still_s: float = 5.0
    calib_move_s: float = 5.0

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.profile = PROFILES.get(self.exercise, PROFILES["SQUAT"])
        self.mount = {"LEFT": random_rotation(self.rng), "RIGHT": random_rotation(self.rng)}
        self.acc_bias = {s: self.rng.normal(0, 0.02, 3) for s in ("LEFT", "RIGHT")}
        self.gyro_bias = {s: self.rng.normal(0, 2.5, 3) for s in ("LEFT", "RIGHT")}
        self.force_gain = {s: 1.0 + self.rng.normal(0, 0.08) for s in ("LEFT", "RIGHT", None)}

    # ------------------------------------------------------------------ #

    def _period(self, side: str) -> float:
        p = self.profile
        if p["pattern"] == "sync":
            # Both legs of a squat move together: one shared period, set by
            # the slower (more affected) side. Only the range differs.
            sev = max(self.left.severity, self.right.severity)
        else:
            sev = (self.left if side == "LEFT" else self.right).severity
        return p["period"] * (1.0 + 0.2 * sev)

    def _active(self, side: str, t: float, period: float) -> float:
        """0/1 envelope: which side is moving now (unilateral exercises).

        Sets are whole numbers of that side's own period, so a side always
        stops at the bottom of a repetition (sin^2 = 0), never mid-movement.
        """
        if self.profile["pattern"] != "unilateral":
            return 1.0
        reps_per_set = 4
        own = period
        other = self._period("RIGHT" if side == "LEFT" else "LEFT")
        cycle = reps_per_set * (self._period("LEFT") + self._period("RIGHT"))
        tc = t % cycle
        left_len = reps_per_set * self._period("LEFT")
        if side == "LEFT":
            return 1.0 if tc < left_len else 0.0
        del own, other
        return 1.0 if tc >= left_len else 0.0

    def tilt(self, side: str, t: float) -> float:
        """Ground-truth segment tilt (deg) at movement time t (t < 0: still)."""
        if t < 0:
            return 0.0
        cfg = self.left if side == "LEFT" else self.right
        p = self.profile
        amp = p["amp"] * (1.0 - 0.6 * cfg.severity)
        period = self._period(side)
        tt = t - cfg.delay_s
        if tt < 0:
            return 0.0
        # Ease in over the first second so movement onset is continuous; a
        # step in tilt would imply infinite angular velocity.
        ramp = min(1.0, tt / 1.0)
        ramp = ramp * ramp * (3 - 2 * ramp)
        if p["pattern"] == "alternate":
            phase = 2 * math.pi * tt / period + (0.0 if side == "LEFT" else math.pi)
            return ramp * amp * (0.55 * math.sin(phase) + 0.25 * math.sin(2 * phase - 0.6))
        if p["pattern"] == "sway":
            return ramp * (amp * math.sin(2 * math.pi * tt / period)
                           + 0.5 * amp * math.sin(2 * math.pi * tt / 1.3))
        active = self._active(side, tt, period)
        if p["pattern"] == "unilateral":
            # Phase restarts at the beginning of each of this side's sets.
            cycle = 4 * (self._period("LEFT") + self._period("RIGHT"))
            tc = tt % cycle
            tt = tc if side == "LEFT" else tc - 4 * self._period("LEFT")
        phase = 2 * math.pi * tt / period
        wobble = 1.0 + 0.05 * math.sin(0.37 * phase)
        return active * amp * wobble * math.sin(phase / 2.0) ** 2

    def _imu(self, side: str, t: float, dt: float, speed: float = 1.0) -> np.ndarray:
        # Derivatives are taken in *device* time: during the slowed-down
        # calibration movement, movement time advances `speed` x device time.
        dte = dt * speed
        th0, th1, th2 = (self.tilt(side, t - dte), self.tilt(side, t), self.tilt(side, t + dte))
        w = (th2 - th0) / (2 * dt)                      # deg/s
        alpha = (th2 - 2 * th1 + th0) / (dt * dt)        # deg/s^2
        r_seg = rot_y(th1)
        # Specific force in world frame (g units): +1 g up, plus rotation of a
        # point LEVER_M from the joint (tangential + centripetal).
        a_tan = LEVER_M * math.radians(alpha) / G
        a_cen = LEVER_M * math.radians(w) ** 2 / G
        f_seg = r_seg.T @ np.array([0.0, 0.0, 1.0]) + np.array([a_tan, 0.0, -a_cen])
        if self.exercise == "WALK" and t >= 0:
            # Vertical body bounce at step frequency.
            f_seg += r_seg.T @ np.array([0, 0, 0.12 * math.sin(4 * math.pi * t / self.profile["period"])])
        w_seg = np.array([0.0, w, 0.0])
        m = self.mount[side]
        cfg = self.left if side == "LEFT" else self.right
        acc = m.T @ f_seg + self.acc_bias[side] + self.rng.normal(0, 0.006 * cfg.noise_scale, 3)
        gyr = m.T @ w_seg + self.gyro_bias[side] + self.rng.normal(0, 0.15 * cfg.noise_scale, 3)
        # The real sensor saturates at full scale (+-4 g, +-500 deg/s).
        acc = np.clip(np.round(acc / ACC_LSB_G) * ACC_LSB_G, -4.0, 4.0 - ACC_LSB_G)
        gyr = np.clip(np.round(gyr / GYRO_LSB_DPS) * GYRO_LSB_DPS, -500.0, 500.0 - GYRO_LSB_DPS)
        return np.concatenate([acc, gyr])

    def _force(self, side: str | None, t: float) -> float:
        """FSR402-like normalised ADC load proxy."""
        if t < 0:
            load = 0.35
        elif self.profile["pattern"] == "alternate":
            # Heel load during stance (tilt below its mean).
            th = self.tilt(side or "LEFT", t)
            load = 0.9 if th < 0 else 0.05
        else:
            depth = abs(self.tilt(side or "LEFT", t)) / max(self.profile["amp"], 1e-6)
            load = 0.35 + 0.55 * depth
            cfg = self.left if side == "LEFT" else self.right
            load *= (1.0 - 0.5 * cfg.severity)
        load *= self.force_gain[side]
        v = 1.0 - math.exp(-2.2 * max(0.0, load))
        return float(min(1.0, max(0.0, v + self.rng.normal(0, 0.004))))

    def sample(self, t_device: float) -> dict:
        """One device tick at device time t (s since stream start)."""
        dt = 1.0 / self.rate_hz
        t_move = t_device - self.still_s
        speed = 1.0
        if 0 <= t_move < self.calib_move_s:
            # Calibration movement: the same exercise, slowed down.
            speed = 0.6
            t_eff = t_move * speed
        elif t_move >= self.calib_move_s:
            t_eff = t_move - self.calib_move_s + self.calib_move_s * 0.6
        else:
            t_eff = -1.0
        out = {}
        for side, key in (("LEFT", "imu_left"), ("RIGHT", "imu_right")):
            cfg = self.left if side == "LEFT" else self.right
            if not cfg.present:
                out[key] = None
                continue
            v = self._imu(side, t_eff, dt, speed)
            out[key] = dict(zip(("ax", "ay", "az", "gx", "gy", "gz"), (round(float(x), 5) for x in v)))
        out["force"] = [round(self._force(s, t_eff), 4) for s in self.force_sides]
        return out
