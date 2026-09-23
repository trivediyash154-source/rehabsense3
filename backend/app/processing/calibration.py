"""Per-session, per-leg, per-segment calibration.

Implements the documented MVP stages: static gyro-bias estimation over the
first ~2.5 s after a node connects, plus accelerometer gravity normalisation.
Full functional (mechanical) alignment is explicitly a later phase and is
reported as such rather than silently pretended.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field

from app.hardware.protocol import SegmentSample


class CalibrationState(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass
class SegmentCalibration:
    """Bias and scale for one IMU (thigh or shin) on one leg."""

    gyro_bias: tuple[float, float, float] = (0.0, 0.0, 0.0)
    accel_scale: float = 1.0
    samples_seen: int = 0
    # RMS of the gyro during the still window: lower means the limb was
    # genuinely stationary, so the bias estimate is trustworthy.
    stillness_rms: float | None = None

    def apply(self, sample: SegmentSample) -> SegmentSample:
        return SegmentSample(
            ax=sample.ax * self.accel_scale,
            ay=sample.ay * self.accel_scale,
            az=sample.az * self.accel_scale,
            gx=sample.gx - self.gyro_bias[0],
            gy=sample.gy - self.gyro_bias[1],
            gz=sample.gz - self.gyro_bias[2],
        )


@dataclass
class LegCalibrator:
    """Collects the calibration window for one leg, then freezes the result."""

    window_seconds: float = 2.5
    state: CalibrationState = CalibrationState.PENDING
    thigh: SegmentCalibration = field(default_factory=SegmentCalibration)
    shin: SegmentCalibration = field(default_factory=SegmentCalibration)
    quality: float | None = None

    _start_ts: float | None = field(default=None, init=False)
    _acc: dict[str, list[SegmentSample]] = field(
        default_factory=lambda: {"thigh": [], "shin": []}, init=False
    )

    @property
    def progress(self) -> float:
        if self.state is CalibrationState.COMPLETE:
            return 1.0
        if self._start_ts is None:
            return 0.0
        return min(1.0, self._elapsed / self.window_seconds)

    _elapsed: float = field(default=0.0, init=False)

    def is_complete(self) -> bool:
        return self.state in (CalibrationState.COMPLETE, CalibrationState.FAILED)

    def observe(self, ts: float, thigh: SegmentSample, shin: SegmentSample) -> None:
        """Feed a raw sample into the calibration window."""
        if self.is_complete():
            return
        if self._start_ts is None:
            self._start_ts = ts
            self.state = CalibrationState.IN_PROGRESS
        self._elapsed = max(0.0, ts - self._start_ts)
        self._acc["thigh"].append(thigh)
        self._acc["shin"].append(shin)
        if self._elapsed >= self.window_seconds:
            self._finalise()

    def force_finalise(self) -> None:
        """End calibration early (e.g. the node disconnected mid-window)."""
        if not self.is_complete():
            self._finalise()

    def _finalise(self) -> None:
        qualities = []
        for name, target in (("thigh", self.thigh), ("shin", self.shin)):
            samples = self._acc[name]
            if len(samples) < 5:
                # Too little data to trust: leave identity calibration and say so.
                self.state = CalibrationState.FAILED
                self.quality = 0.0
                return
            n = len(samples)
            target.gyro_bias = (
                sum(s.gx for s in samples) / n,
                sum(s.gy for s in samples) / n,
                sum(s.gz for s in samples) / n,
            )
            magnitudes = [math.sqrt(s.ax**2 + s.ay**2 + s.az**2) for s in samples]
            mean_g = sum(magnitudes) / n
            # Normalise the sensed gravity vector to 1 g.
            target.accel_scale = 1.0 / mean_g if mean_g > 1e-6 else 1.0
            target.samples_seen = n

            centred = [
                math.sqrt(
                    (s.gx - target.gyro_bias[0]) ** 2
                    + (s.gy - target.gyro_bias[1]) ** 2
                    + (s.gz - target.gyro_bias[2]) ** 2
                )
                for s in samples
            ]
            rms = math.sqrt(sum(v * v for v in centred) / n)
            target.stillness_rms = rms
            # ~2 deg/s residual is a still limb; 20 deg/s is not.
            qualities.append(max(0.0, min(1.0, 1.0 - (rms - 2.0) / 18.0)))

        self.quality = sum(qualities) / len(qualities)
        self.state = CalibrationState.COMPLETE
        self._acc = {"thigh": [], "shin": []}

    def apply(self, thigh: SegmentSample, shin: SegmentSample) -> tuple[SegmentSample, SegmentSample]:
        return self.thigh.apply(thigh), self.shin.apply(shin)
