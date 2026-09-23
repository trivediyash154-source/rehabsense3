"""Segment orientation and knee angle.

Implements the documented mathematics exactly:

    theta_acc  = atan2(ax, az)                                  (degrees)
    theta_gyro = theta(t-1) + gy * dt
    theta(t)   = a * (theta(t-1) + gy*dt) + (1 - a) * theta_acc  (a = 0.98)
    theta_knee = theta_shin - theta_thigh

ZUPT resets the integrated gyro contribution during detected stance, which is
what bounds long-run drift.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.hardware.protocol import SegmentSample
from app.processing.filters import VectorLowpass

_CHANNELS = ("ax", "ay", "az", "gx", "gy", "gz")


def inclination_from_accel(sample: SegmentSample) -> float:
    """Sagittal-plane inclination from the gravity vector, in degrees."""
    return math.degrees(math.atan2(sample.ax, sample.az))


@dataclass
class SegmentTracker:
    """Complementary-filter orientation tracker for one IMU."""

    alpha: float = 0.98
    cutoff_hz: float = 5.0
    sample_rate_hz: float = 100.0

    theta: float = 0.0
    _initialised: bool = field(default=False, init=False)
    _lowpass: VectorLowpass = field(init=False)

    def __post_init__(self) -> None:
        self._lowpass = VectorLowpass(_CHANNELS, self.cutoff_hz, self.sample_rate_hz)

    def update(self, sample: SegmentSample, dt: float, zupt: bool = False) -> float:
        """Advance the estimate by one sample and return the new angle."""
        filtered = SegmentSample(
            **self._lowpass(
                {
                    "ax": sample.ax, "ay": sample.ay, "az": sample.az,
                    "gx": sample.gx, "gy": sample.gy, "gz": sample.gz,
                }
            )
        )
        theta_acc = inclination_from_accel(filtered)

        if not self._initialised:
            # Start from gravity rather than zero, so there is no opening ramp.
            self.theta = theta_acc
            self._initialised = True
            return self.theta

        if zupt:
            # Stationary: drop the integrated gyro term and trust gravity.
            # This is the primary long-run drift bound.
            self.theta = theta_acc
            return self.theta

        dt = max(1e-4, min(dt, 0.5))
        theta_gyro = self.theta + filtered.gy * dt
        self.theta = self.alpha * theta_gyro + (1.0 - self.alpha) * theta_acc
        return self.theta


@dataclass
class LegTracker:
    """Thigh + shin trackers producing a relative knee angle.

    Relative measurement is the core of the approach: no fixed world
    reference is needed, and whole-body motion cancels out.
    """

    alpha: float = 0.98
    cutoff_hz: float = 5.0
    sample_rate_hz: float = 100.0
    fsr_stance_threshold: float = 0.15
    # Gyro magnitude below this (deg/s) counts as quasi-stationary.
    zupt_gyro_threshold: float = 12.0

    thigh: SegmentTracker = field(init=False)
    shin: SegmentTracker = field(init=False)
    last_ts: float | None = field(default=None, init=False)
    zupt_count: int = field(default=0, init=False)
    sample_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.thigh = SegmentTracker(self.alpha, self.cutoff_hz, self.sample_rate_hz)
        self.shin = SegmentTracker(self.alpha, self.cutoff_hz, self.sample_rate_hz)

    def detect_stance(self, shin: SegmentSample, fsr: float | None) -> bool:
        """Stance detection: FSR when the node has one, gyro magnitude otherwise.

        The gyro-only branch is the path exercised by default today, not a
        hypothetical fallback.
        """
        if fsr is not None:
            return fsr > self.fsr_stance_threshold
        magnitude = math.sqrt(shin.gx**2 + shin.gy**2 + shin.gz**2)
        return magnitude < self.zupt_gyro_threshold

    def update(
        self, ts: float, thigh: SegmentSample, shin: SegmentSample, fsr: float | None = None
    ) -> tuple[float, bool]:
        """Returns (knee angle in degrees, whether this sample was in stance)."""
        dt = 1.0 / self.sample_rate_hz if self.last_ts is None else ts - self.last_ts
        if dt <= 0:
            dt = 1.0 / self.sample_rate_hz
        self.last_ts = ts

        stance = self.detect_stance(shin, fsr)
        self.thigh.update(thigh, dt, zupt=stance)
        self.shin.update(shin, dt, zupt=stance)

        self.sample_count += 1
        if stance:
            self.zupt_count += 1

        return self.shin.theta - self.thigh.theta, stance

    @property
    def correction_ratio(self) -> float:
        """Share of samples that needed a ZUPT correction.

        Feeds the confidence engine: a stream needing constant correction is
        less trustworthy than one that tracked cleanly.
        """
        if self.sample_count == 0:
            return 0.0
        return self.zupt_count / self.sample_count
