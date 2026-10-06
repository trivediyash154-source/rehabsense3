"""Repetition segmentation and movement phases, from one IMU's tilt signal.

Signal processing, not a trained model. There is no labelled RehabSense
repetition/phase data yet, so a learned phase model would have nothing honest
to learn from; the session-label tables exist so that data can be collected
(see docs/HARDWARE_ML_ARCHITECTURE.md).

Repetitions only make sense for some exercises. WALK produces gait *cycles*
(reported as such), balance holds produce none, and anything not listed is
not segmented at all rather than forced into repetitions.

Phases of one repetition, relative to its amplitude A above its start level:

    rest        |x - start| < 10% A
    initiation  10% -> 30% A, rising
    movement    30% -> 90% A, rising
    peak        >= 90% A
    return      falling from 90% A back to 10% A
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass

import numpy as np

DETECTOR_VERSION = "rep-peak-v1"
PHASES = ("rest", "initiation", "movement", "peak", "return")


class RepMode(str, enum.Enum):
    REPETITION = "REPETITION"
    GAIT_CYCLE = "GAIT_CYCLE"
    NONE = "NONE"


class BilateralMode(str, enum.Enum):
    """How the two legs are expected to move relative to each other."""

    SYNCHRONOUS = "SYNCHRONOUS"   # both together (squat, sit-to-stand)
    ALTERNATING = "ALTERNATING"   # half a cycle apart (walking)
    UNILATERAL = "UNILATERAL"     # one side at a time; compare per-side aggregates


EXERCISE_REP_MODE = {
    "SQUAT": RepMode.REPETITION,
    "SIT_TO_STAND": RepMode.REPETITION,
    "STEP_UP": RepMode.REPETITION,
    "KNEE_EXTENSION": RepMode.REPETITION,
    "WALK": RepMode.GAIT_CYCLE,
    "SINGLE_LEG_BALANCE": RepMode.NONE,
}

EXERCISE_BILATERAL_MODE = {
    "SQUAT": BilateralMode.SYNCHRONOUS,
    "SIT_TO_STAND": BilateralMode.SYNCHRONOUS,
    "WALK": BilateralMode.ALTERNATING,
    "STEP_UP": BilateralMode.UNILATERAL,
    "KNEE_EXTENSION": BilateralMode.UNILATERAL,
    "SINGLE_LEG_BALANCE": BilateralMode.UNILATERAL,
}

# Shortest plausible repetition / cycle, seconds.
MIN_PERIOD_S = {RepMode.REPETITION: 0.8, RepMode.GAIT_CYCLE: 0.6}
# Smallest tilt excursion that counts as a repetition, degrees.
MIN_AMPLITUDE_DEG = {RepMode.REPETITION: 10.0, RepMode.GAIT_CYCLE: 8.0}


@dataclass
class Rep:
    side: str
    index: int
    t_start: float
    t_peak: float
    t_end: float
    amplitude_deg: float
    peak_velocity_dps: float
    mean_abs_velocity_dps: float
    smoothness_sparc: float | None
    phase_durations_s: dict
    phase_segments: list | None = None
    force_peak: float | None = None
    force_peak_lag_s: float | None = None
    # Time-normalised tilt trace (51 points) for consistency comparisons.
    profile: list | None = None

    @property
    def duration_s(self) -> float:
        return self.t_end - self.t_start

    def as_dict(self) -> dict:
        return {
            "side": self.side,
            "rep_index": self.index,
            "t_start": round(self.t_start, 3),
            "t_peak": round(self.t_peak, 3),
            "t_end": round(self.t_end, 3),
            "duration_s": round(self.duration_s, 3),
            "rom_proxy_deg": round(self.amplitude_deg, 2),
            "peak_velocity_dps": round(self.peak_velocity_dps, 1),
            "mean_abs_velocity_dps": round(self.mean_abs_velocity_dps, 1),
            "smoothness_sparc": (
                None if self.smoothness_sparc is None else round(self.smoothness_sparc, 3)
            ),
            "phase_durations_s": self.phase_durations_s,
            "force_peak": None if self.force_peak is None else round(self.force_peak, 4),
            "force_peak_lag_s": (
                None if self.force_peak_lag_s is None else round(self.force_peak_lag_s, 3)
            ),
            "detector_version": DETECTOR_VERSION,
        }


def movement_sign(tilt: np.ndarray) -> float:
    """+1 if the movement goes positive from neutral (0 deg), else -1."""
    t = tilt[np.isfinite(tilt)]
    if len(t) == 0:
        return 1.0
    return -1.0 if abs(float(np.percentile(t, 2))) > abs(float(np.percentile(t, 98))) else 1.0


def find_peaks(x: np.ndarray, min_prominence: float, min_distance: int) -> list[int]:
    """Local maxima with at least `min_prominence`, `min_distance` apart.

    A small stand-in for scipy.signal.find_peaks (scipy is not installable on
    this Python; see requirements.txt).
    """
    n = len(x)
    if n < 3:
        return []
    cand = [i for i in range(1, n - 1) if x[i] > x[i - 1] and x[i] >= x[i + 1]]
    kept = []
    for i in cand:
        left_min = x[: i + 1][::-1]
        right_min = x[i:]
        # Prominence: drop to the lowest point before reaching higher ground.
        lb = x[i]
        for v in left_min[1:]:
            if v > x[i]:
                break
            lb = min(lb, v)
        rb = x[i]
        for v in right_min[1:]:
            if v > x[i]:
                break
            rb = min(rb, v)
        if x[i] - max(lb, rb) >= min_prominence:
            kept.append(i)
    # Enforce spacing, tallest first.
    kept.sort(key=lambda i: -x[i])
    chosen: list[int] = []
    for i in kept:
        if all(abs(i - j) >= min_distance for j in chosen):
            chosen.append(i)
    return sorted(chosen)


def sparc(speed: np.ndarray, rate: float, fc: float = 10.0, amp_th: float = 0.05) -> float | None:
    """Spectral arc length (Balasubramanian et al., 2015). Closer to 0 = smoother.

    Dimensionless and independent of movement amplitude and duration, which
    is why it was chosen over jerk-based measures.
    """
    if len(speed) < 8 or not np.isfinite(speed).all() or np.max(np.abs(speed)) < 1e-6:
        return None
    nfft = int(2 ** (np.ceil(np.log2(len(speed))) + 4))
    f = np.arange(0, rate, rate / nfft)
    mag = np.abs(np.fft.fft(speed, nfft))
    mag = mag / max(mag.max(), 1e-12)
    sel = f <= fc
    f, mag = f[sel], mag[sel]
    above = np.nonzero(mag >= amp_th)[0]
    if len(above) == 0:
        return None
    f, mag = f[: above[-1] + 1], mag[: above[-1] + 1]
    df = np.diff(f) / (f[-1] - f[0] if f[-1] > f[0] else 1.0)
    dm = np.diff(mag)
    return float(-np.sum(np.sqrt(df ** 2 + dm ** 2)))


def segment_phases(t: np.ndarray, x: np.ndarray, peak_i: int) -> list[tuple[str, float, float]]:
    """Contiguous (phase, t_start, t_end) spans of one repetition."""
    start = x[0]
    amp = x[peak_i] - start
    if amp <= 0 or len(x) < 2:
        return []
    rel = (x - start) / amp
    labels = []
    for i in range(len(x)):
        if rel[i] >= 0.9:
            labels.append("peak")
        elif i <= peak_i:
            labels.append("rest" if rel[i] < 0.1 else "initiation" if rel[i] < 0.3 else "movement")
        else:
            labels.append("return" if rel[i] >= 0.1 else "rest")
    segs: list[tuple[str, float, float]] = []
    seg_start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[seg_start]:
            t_end = float(t[i]) if i < len(t) else float(t[-1])
            segs.append((labels[seg_start], float(t[seg_start]), t_end))
            seg_start = i
    return segs


def _phase_durations(segs: list[tuple[str, float, float]]) -> dict:
    out = {p: 0.0 for p in PHASES}
    for p, a, b in segs:
        out[p] += b - a
    return {k: round(v, 3) for k, v in out.items()}


def current_phase(x_recent: np.ndarray, reference_amplitude: float | None,
                  rest_level: float | None) -> str | None:
    """Phase of the most recent sample, given the recent rep amplitude."""
    if reference_amplitude is None or rest_level is None or len(x_recent) < 3:
        return None
    if reference_amplitude <= 0:
        return None
    rel = (x_recent[-1] - rest_level) / reference_amplitude
    rising = x_recent[-1] >= x_recent[-3]
    if rel >= 0.9:
        return "peak"
    if rel < 0.1:
        return "rest"
    if rising:
        return "initiation" if rel < 0.3 else "movement"
    return "return"


def detect_reps(side: str, t: np.ndarray, tilt: np.ndarray, w_axis: np.ndarray,
                rate: float, mode: RepMode, force: np.ndarray | None = None,
                start_index: int = 0) -> list[Rep]:
    """Segment repetitions (or gait cycles) from a tilt trace.

    The tilt is oriented so the movement goes *away* from neutral as a
    positive excursion: if the trace mostly moves negative, it is flipped.
    """
    if mode is RepMode.NONE or len(t) < int(rate * 1.5):
        return []
    x = tilt.copy()
    # Tilt is measured from the calibrated neutral pose (0 deg), so a
    # repetition is an excursion away from 0; flip so it is positive.
    if movement_sign(x) < 0:
        x = -x
        w_axis = -w_axis
    span = float(np.percentile(x, 95) - np.percentile(x, 5))
    min_amp = MIN_AMPLITUDE_DEG[mode]
    if span < min_amp:
        return []
    prom = max(min_amp, 0.35 * span)
    dist = max(2, int(MIN_PERIOD_S[mode] * rate))
    peaks = find_peaks(x, prom, dist)
    reps: list[Rep] = []
    for k, p in enumerate(peaks):
        lo = peaks[k - 1] if k > 0 else 0
        hi = peaks[k + 1] if k + 1 < len(peaks) else len(x) - 1
        s = lo + int(np.argmin(x[lo:p + 1]))
        e = p + int(np.argmin(x[p:hi + 1]))
        # Amplitude from the true troughs, before any trimming.
        amp = float(x[p] - min(x[s], x[e]))
        # Trim idle time: the repetition starts where the trace last leaves
        # its trough level and ends where it first returns to it, so a pause
        # between sets is not counted as part of the movement.
        rise = x[p] - x[s]
        fall = x[p] - x[e]
        if rise > 0:
            leave = np.nonzero(x[s:p + 1] <= x[s] + 0.05 * rise)[0]
            s = s + int(leave[-1]) if len(leave) else s
        if fall > 0:
            back = np.nonzero(x[p:e + 1] <= x[e] + 0.05 * fall)[0]
            e = p + int(back[0]) if len(back) else e
        # Require the trace to come back down: an unfinished rep is not a rep.
        if e <= p or x[p] - x[e] < 0.5 * (x[p] - x[s]) or (k + 1 == len(peaks) and e == len(x) - 1):
            continue
        seg_t, seg_x, seg_w = t[s:e + 1], x[s:e + 1], w_axis[s:e + 1]
        if amp < min_amp:
            continue
        grid = np.linspace(seg_t[0], seg_t[-1], 51)
        profile = np.interp(grid, seg_t, seg_x)
        profile = (profile - profile.min()) / max(np.ptp(profile), 1e-9)
        rep = Rep(
            side=side, index=start_index + len(reps) + 1,
            t_start=float(seg_t[0]), t_peak=float(t[p]), t_end=float(seg_t[-1]),
            amplitude_deg=amp,
            peak_velocity_dps=float(np.max(np.abs(seg_w))),
            mean_abs_velocity_dps=float(np.mean(np.abs(seg_w))),
            smoothness_sparc=sparc(np.abs(seg_w), rate),
            phase_durations_s=_phase_durations(segment_phases(seg_t, seg_x, p - s)),
            phase_segments=segment_phases(seg_t, seg_x, p - s),
            profile=[round(float(v), 4) for v in profile],
        )
        if force is not None and len(force) == len(t):
            seg_f = force[s:e + 1]
            if np.isfinite(seg_f).sum() > 3:
                fi = int(np.nanargmax(seg_f))
                rep.force_peak = float(seg_f[fi])
                rep.force_peak_lag_s = float(seg_t[fi] - t[p])
        reps.append(rep)
    return reps


def profile_consistency(reps: list[Rep]) -> float | None:
    """Mean pairwise correlation of time-normalised rep profiles, clipped at 0."""
    profiles = [np.asarray(r.profile) for r in reps if r.profile]
    if len(profiles) < 3:
        return None
    m = np.vstack(profiles)
    c = np.corrcoef(m)
    iu = np.triu_indices(len(m), 1)
    vals = c[iu]
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return None
    return float(max(0.0, np.mean(vals)))


def coefficient_of_variation(values: list[float]) -> float | None:
    v = [x for x in values if x is not None and math.isfinite(x)]
    if len(v) < 3:
        return None
    mean = float(np.mean(v))
    if abs(mean) < 1e-9:
        return None
    return float(np.std(v) / abs(mean))
