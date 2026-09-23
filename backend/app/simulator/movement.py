"""Physiologically-shaped movement generation.

Produces thigh and shin inclination curves, then derives accelerometer and
gyroscope readings that are *consistent* with those curves:

    ax = sin(theta), az = cos(theta)   so atan2(ax, az) recovers theta
    gy = d(theta)/dt                    so integrating gy recovers theta

That consistency is the point: it means the backend's complementary filter is
genuinely reconstructing a known ground-truth angle, so a test can assert the
recovered knee angle against the angle that was generated. Random noise would
prove nothing.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# Peak knee flexion for a healthy limb, per exercise (degrees).
EXERCISE_PROFILE: dict[str, dict] = {
    "WALK": {"peak": 62.0, "period": 1.15, "duty": 0.62},
    "SQUAT": {"peak": 95.0, "period": 3.0, "duty": 0.5},
    "SIT_TO_STAND": {"peak": 88.0, "period": 3.4, "duty": 0.5},
    "STEP_UP": {"peak": 78.0, "period": 2.4, "duty": 0.55},
    "KNEE_EXTENSION": {"peak": 85.0, "period": 2.8, "duty": 0.5},
    "SINGLE_LEG_BALANCE": {"peak": 14.0, "period": 6.0, "duty": 0.5},
}


@dataclass
class LimbModel:
    """Generates one limb's segment inclinations over time."""

    exercise: str
    severity: float = 0.0          # 0 = unaffected, 1 = severely restricted
    phase_offset: float = 0.0      # radians; the two limbs are offset in gait
    noise_deg: float = 0.35
    rng: random.Random | None = None

    def __post_init__(self) -> None:
        profile = EXERCISE_PROFILE.get(self.exercise, EXERCISE_PROFILE["SQUAT"])
        self.peak = profile["peak"] * (1.0 - 0.55 * self.severity)
        self.period = profile["period"] * (1.0 + 0.25 * self.severity)
        self.rng = self.rng or random.Random(0)

    def knee_angle(self, t: float) -> float:
        """Ground-truth knee flexion at time t (degrees)."""
        phase = (2 * math.pi * t / self.period) + self.phase_offset
        # sin^2 gives a smooth, always-positive flexion cycle.
        base = math.pow(math.sin(phase / 2.0), 2) * self.peak
        # A little cycle-to-cycle variation, as real movement has.
        wobble = 0.04 * self.peak * math.sin(phase * 0.37)
        return max(0.0, base + wobble)

    def segments(self, t: float) -> tuple[float, float]:
        """(thigh inclination, shin inclination) in degrees.

        The thigh swings modestly; the shin carries the thigh's motion plus
        the knee angle, so shin - thigh reproduces the knee angle exactly.
        """
        phase = (2 * math.pi * t / self.period) + self.phase_offset
        thigh = 12.0 * math.sin(phase) * (1.0 - 0.3 * self.severity)
        shin = thigh + self.knee_angle(t)
        return thigh, shin

    def stance(self, t: float) -> bool:
        """Ground contact for gait-type movement."""
        profile = EXERCISE_PROFILE.get(self.exercise, EXERCISE_PROFILE["SQUAT"])
        phase = ((2 * math.pi * t / self.period) + self.phase_offset) % (2 * math.pi)
        return phase < 2 * math.pi * profile["duty"]

    def imu(self, t: float, dt: float, noisy: bool = True) -> tuple[dict, dict]:
        """Derive accel (g) and gyro (deg/s) for both segments at time t."""
        thigh_a, shin_a = self.segments(t)
        thigh_b, shin_b = self.segments(t + dt)

        def build(theta_now: float, theta_next: float) -> dict:
            rad = math.radians(theta_now)
            gy = (theta_next - theta_now) / dt  # deg/s
            n = (lambda: self.rng.gauss(0.0, self.noise_deg * 0.01)) if noisy else (lambda: 0.0)
            g = (lambda: self.rng.gauss(0.0, self.noise_deg)) if noisy else (lambda: 0.0)
            return {
                "ax": math.sin(rad) + n(),
                "ay": 0.0 + n(),
                "az": math.cos(rad) + n(),
                "gx": 0.0 + g(),
                "gy": gy + g(),
                "gz": 0.0 + g(),
            }

        return build(thigh_a, thigh_b), build(shin_a, shin_b)

    def still_imu(self) -> tuple[dict, dict]:
        """A stationary limb, for the calibration window.

        Carries a small constant gyro bias — exactly what calibration exists
        to estimate and remove.
        """
        bias = (0.8, -0.5, 0.3)
        def build() -> dict:
            return {
                "ax": 0.0 + self.rng.gauss(0.0, 0.004),
                "ay": 0.0 + self.rng.gauss(0.0, 0.004),
                "az": 1.0 + self.rng.gauss(0.0, 0.004),
                "gx": bias[0] + self.rng.gauss(0.0, 0.25),
                "gy": bias[1] + self.rng.gauss(0.0, 0.25),
                "gz": bias[2] + self.rng.gauss(0.0, 0.25),
            }
        return build(), build()
