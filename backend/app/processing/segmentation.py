"""Repetition and gait segmentation.

Repetitions are segmented by threshold crossing plus peak detection on the
knee angle, and every value is computed over the *whole* cycle. A rep's ROM
is max−min across its window — never a single boundary sample, which would
report the trough as the peak.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field


class MovementType(str, enum.Enum):
    GAIT = "GAIT"
    REPETITION = "REPETITION"
    HOLD = "HOLD"


EXERCISE_MOVEMENT: dict[str, MovementType] = {
    "WALK": MovementType.GAIT,
    "SQUAT": MovementType.REPETITION,
    "SIT_TO_STAND": MovementType.REPETITION,
    "STEP_UP": MovementType.REPETITION,
    "KNEE_EXTENSION": MovementType.REPETITION,
    "SINGLE_LEG_BALANCE": MovementType.HOLD,
}


@dataclass
class Repetition:
    index: int
    start_t: float
    end_t: float
    peak_angle: float
    min_angle: float
    rom: float
    duration: float
    smoothness: float
    quality: float


@dataclass
class RepetitionSegmenter:
    """Hysteresis state machine over the knee-angle signal.

    Two thresholds prevent a noisy signal from chattering across a single
    boundary and producing phantom repetitions.
    """

    enter_threshold: float = 25.0   # rising past this opens a repetition
    exit_threshold: float = 15.0    # falling below this closes it
    min_duration_s: float = 0.35
    min_rom_deg: float = 12.0

    index: int = field(default=0, init=False)
    _active: bool = field(default=False, init=False)
    _start_t: float | None = field(default=None, init=False)
    _angles: list[float] = field(default_factory=list, init=False)
    _times: list[float] = field(default_factory=list, init=False)
    completed: list[Repetition] = field(default_factory=list, init=False)

    def update(self, t: float, angle: float) -> Repetition | None:
        """Feed one sample. Returns a Repetition at the moment one closes."""
        if not self._active:
            if angle >= self.enter_threshold:
                self._active = True
                self._start_t = t
                self._angles = [angle]
                self._times = [t]
            return None

        self._angles.append(angle)
        self._times.append(t)

        if angle <= self.exit_threshold:
            return self._close(t)
        return None

    def _close(self, t: float) -> Repetition | None:
        angles = self._angles
        start = self._start_t if self._start_t is not None else t
        duration = t - start
        self._active = False
        self._start_t = None

        if not angles:
            return None

        peak = max(angles)
        low = min(angles)
        rom = peak - low

        # Reject noise blips rather than logging them as repetitions.
        if duration < self.min_duration_s or rom < self.min_rom_deg:
            self._angles, self._times = [], []
            return None

        self.index += 1
        rep = Repetition(
            index=self.index,
            start_t=start,
            end_t=t,
            peak_angle=peak,
            min_angle=low,
            rom=rom,
            duration=duration,
            smoothness=_smoothness(angles, self._times),
            quality=0.0,
        )
        rep.quality = _quality(rep)
        self.completed.append(rep)
        self._angles, self._times = [], []
        return rep

    def flush(self, t: float) -> Repetition | None:
        """Close an in-flight repetition at session end."""
        if self._active:
            return self._close(t)
        return None


def _smoothness(angles: list[float], times: list[float]) -> float:
    """Inverse normalised jerk over the repetition, mapped to 0..1.

    Jerk is the second derivative of the angle: a controlled movement has low
    second-derivative energy, a jerky one has high.
    """
    if len(angles) < 4:
        return 0.5
    accels = []
    for i in range(1, len(angles) - 1):
        dt1 = max(1e-3, times[i] - times[i - 1])
        dt2 = max(1e-3, times[i + 1] - times[i])
        v1 = (angles[i] - angles[i - 1]) / dt1
        v2 = (angles[i + 1] - angles[i]) / dt2
        accels.append((v2 - v1) / ((dt1 + dt2) / 2.0))
    if not accels:
        return 0.5
    rms = math.sqrt(sum(a * a for a in accels) / len(accels))
    span = max(1.0, max(angles) - min(angles))
    normalised = rms / (span * 40.0)
    return max(0.0, min(1.0, 1.0 / (1.0 + normalised)))


def _quality(rep: Repetition) -> float:
    """Illustrative movement-quality score: depth and smoothness, 0..1.

    Explicitly a decision-support estimate, not a clinical grade.
    """
    depth = max(0.0, min(1.0, rep.rom / 90.0))
    tempo = 1.0 if 0.6 <= rep.duration <= 4.0 else 0.7
    return round(max(0.0, min(1.0, 0.55 * depth + 0.35 * rep.smoothness + 0.10 * tempo)), 3)


@dataclass
class GaitCycle:
    index: int
    start_t: float
    end_t: float
    stride_s: float
    stance_s: float
    swing_s: float


@dataclass
class GaitSegmenter:
    """Gait events from the stance signal.

    Stance comes from the FSR when the node has one, and from the shin gyro
    magnitude otherwise — the same signal the ZUPT trigger uses.
    """

    min_stride_s: float = 0.4
    max_stride_s: float = 3.0

    index: int = field(default=0, init=False)
    _in_stance: bool = field(default=False, init=False)
    _stance_start: float | None = field(default=None, init=False)
    _cycle_start: float | None = field(default=None, init=False)
    _stance_accum: float = field(default=0.0, init=False)
    cycles: list[GaitCycle] = field(default_factory=list, init=False)

    def update(self, t: float, stance: bool) -> GaitCycle | None:
        """Heel-strike proxy = stance onset; a stride spans onset to onset."""
        cycle: GaitCycle | None = None

        if stance and not self._in_stance:
            # Heel strike.
            if self._cycle_start is not None:
                stride = t - self._cycle_start
                if self.min_stride_s <= stride <= self.max_stride_s:
                    self.index += 1
                    stance_s = min(self._stance_accum, stride)
                    cycle = GaitCycle(
                        index=self.index,
                        start_t=self._cycle_start,
                        end_t=t,
                        stride_s=stride,
                        stance_s=stance_s,
                        swing_s=max(0.0, stride - stance_s),
                    )
                    self.cycles.append(cycle)
            self._cycle_start = t
            self._stance_accum = 0.0
            self._stance_start = t
            self._in_stance = True

        elif not stance and self._in_stance:
            # Toe off.
            if self._stance_start is not None:
                self._stance_accum += t - self._stance_start
            self._in_stance = False
            self._stance_start = None

        elif stance and self._in_stance and self._stance_start is not None:
            pass  # accumulated on toe-off

        return cycle

    def cadence_spm(self, window: int = 6) -> float | None:
        """Steps per minute from recent strides. One stride = two steps."""
        if len(self.cycles) < 2:
            return None
        recent = self.cycles[-window:]
        mean_stride = sum(c.stride_s for c in recent) / len(recent)
        if mean_stride <= 0:
            return None
        return round(120.0 / mean_stride, 1)
