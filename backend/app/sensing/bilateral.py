"""Left/right comparison from the two MPU6050s.

A research/engineering metric, not a clinical measure of anything. It is only
ever computed from two *real* simultaneous streams on the same device clock.
A one-sided stream returns status SINGLE_SIDE and no score: there is nothing
to compare, and inventing a number (or mirroring one side) would be worse
than saying so.

Each component is a normalised difference in [0, 1], 0 = identical:

    nd(L, R) = |L - R| / max(|L|, |R|)

    acc_dynamic_rms       RMS of |a| - 1 g          (impact / dynamic load proxy)
    gyro_rms              RMS of |w|                (overall rotation)
    gyro_peak             95th percentile of |w|    (peak angular velocity)
    rom_proxy             tilt range                (range-of-motion *proxy*)
    waveform              1 - peak cross-correlation of |w|
    timing                lag between sides, relative to what the exercise
                          expects (0 for synchronous, half a cycle for gait)

The score is the unweighted mean of the available components. Equal weights
are deliberate: there is no validated basis yet for weighting one component
over another, and an equal weighting is the assumption that is easiest to
see and to challenge. Every component is returned alongside the score.
"""

from __future__ import annotations

import math

import numpy as np

from app.sensing.repetitions import BilateralMode, Rep

BILATERAL_VERSION = "bilat-v1"
NO_MOVEMENT_DPS = 10.0
# Below these on *both* sides a component is sensor noise, not movement, and
# its normalised difference would be noise divided by noise.
NOISE_FLOOR = {"acc_dynamic_rms": 0.03, "gyro_rms": 5.0, "gyro_peak": 8.0, "rom_proxy": 3.0}
LABEL = "Bilateral asymmetry (research/engineering metric — not a diagnosis)"


def nd(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or not (math.isfinite(a) and math.isfinite(b)):
        return None
    m = max(abs(a), abs(b))
    if m < 1e-9:
        return 0.0
    return float(min(1.0, abs(a - b) / m))


def _larger(a, b):
    if a is None or b is None:
        return None
    if abs(a - b) < 1e-9:
        return "EQUAL"
    return "LEFT" if a > b else "RIGHT"


def _period(sig: np.ndarray, rate: float) -> float | None:
    x = sig - sig.mean()
    n = len(x)
    if n < rate:
        return None
    ac = np.correlate(x, x, mode="full")[n - 1:]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]
    lo, hi = int(0.4 * rate), min(n - 1, int(3.0 * rate))
    if hi <= lo:
        return None
    k = lo + int(np.argmax(ac[lo:hi]))
    return None if ac[k] < 0.3 else k / rate


def _xcorr(a: np.ndarray, b: np.ndarray, rate: float, max_lag_s: float):
    a = a - a.mean()
    b = b - b.mean()
    denom = math.sqrt(float((a * a).sum() * (b * b).sum()))
    if denom < 1e-12:
        return None, None
    full = np.correlate(a, b, mode="full") / denom
    lags = np.arange(-len(b) + 1, len(a))
    sel = np.abs(lags) <= int(max_lag_s * rate)
    i = int(np.argmax(full[sel]))
    return float(full[sel][i]), float(lags[sel][i] / rate)


def window_asymmetry(left: np.ndarray, right: np.ndarray, tilt_l: np.ndarray | None,
                     tilt_r: np.ndarray | None, rate: float, mode: BilateralMode,
                     availability: dict[str, float]) -> dict:
    """Asymmetry over one uniformly-resampled window of both IMUs."""
    out = {"version": BILATERAL_VERSION, "label": LABEL, "mode": mode.value,
           "components": {}, "larger_side": {}}
    if availability.get("LEFT", 0) < 0.9 or availability.get("RIGHT", 0) < 0.9:
        return {**out, "status": "SINGLE_SIDE", "asymmetry_score": None, "confidence": 0.0,
                "message": "Both IMUs are required for a bilateral comparison."}
    if np.isnan(left).any() or np.isnan(right).any():
        return {**out, "status": "INSUFFICIENT_DATA", "asymmetry_score": None, "confidence": 0.0,
                "message": "Window has gaps on one side."}

    gl = np.linalg.norm(left[:, 3:6], axis=1)
    gr = np.linalg.norm(right[:, 3:6], axis=1)
    if np.sqrt(np.mean(gl ** 2)) < NO_MOVEMENT_DPS and np.sqrt(np.mean(gr ** 2)) < NO_MOVEMENT_DPS:
        return {**out, "status": "NO_MOVEMENT", "asymmetry_score": None, "confidence": 0.0,
                "message": "Neither side is moving; nothing to compare."}

    al = np.linalg.norm(left[:, 0:3], axis=1) - 1.0
    ar = np.linalg.norm(right[:, 0:3], axis=1) - 1.0
    vals = {
        "acc_dynamic_rms": (float(np.sqrt(np.mean(al ** 2))), float(np.sqrt(np.mean(ar ** 2)))),
        "gyro_rms": (float(np.sqrt(np.mean(gl ** 2))), float(np.sqrt(np.mean(gr ** 2)))),
        "gyro_peak": (float(np.percentile(gl, 95)), float(np.percentile(gr, 95))),
    }
    if tilt_l is not None and tilt_r is not None and np.isfinite(tilt_l).all() and np.isfinite(tilt_r).all():
        vals["rom_proxy"] = (float(np.ptp(tilt_l)), float(np.ptp(tilt_r)))

    comps = {}
    for k, (lv, rv) in vals.items():
        floor = NOISE_FLOOR.get(k, 0.0)
        comps[k] = None if max(abs(lv), abs(rv)) < floor else nd(lv, rv)
        out["larger_side"][k] = _larger(lv, rv)
        out.setdefault("values", {})[k] = {"left": round(lv, 4), "right": round(rv, 4)}

    if mode is not BilateralMode.UNILATERAL:
        # Per-leg period: the *sum* of both legs repeats every step, which is
        # half a stride during gait and would fold the expected lag to zero.
        periods = [p for p in (_period(gl, rate), _period(gr, rate)) if p]
        period = float(np.mean(periods)) if periods else None
        peak, lag = _xcorr(gl, gr, rate, max_lag_s=1.5)
        if peak is not None:
            # Peak over lags, so a gait half-cycle shift is aligned away and
            # only the shape is compared; the shift itself is `timing`.
            comps["waveform"] = float(min(1.0, max(0.0, 1.0 - peak)))
        if lag is not None and period:
            # Distance of the lag from the nearest whole cycle, in [0, P/2].
            folded = abs(((lag + period / 2) % period) - period / 2)
            if mode is BilateralMode.SYNCHRONOUS:
                timing = min(1.0, folded / (period / 2))
            else:
                # Legs are expected half a cycle apart.
                timing = min(1.0, abs(folded - period / 2) / (period / 2))
            comps["timing"] = float(timing)
            out["timing"] = {"lag_s": round(lag, 3), "period_s": round(period, 3)}

    available = [v for v in comps.values() if v is not None]
    score = float(np.mean(available)) if available else None
    seconds = len(gl) / rate
    conf = min(1.0, seconds / 4.0) * min(availability.values()) * (len(available) / 6.0) ** 0.5
    out["components"] = {k: None if v is None else round(v, 4) for k, v in comps.items()}
    return {**out, "status": "OK", "asymmetry_score": None if score is None else round(score, 4),
            "confidence": round(float(min(1.0, conf)), 3)}


def rep_asymmetry(left_reps: list[Rep], right_reps: list[Rep]) -> dict:
    """Per-side repetition aggregates, for UNILATERAL exercises and summaries."""
    out = {"version": BILATERAL_VERSION, "label": LABEL, "components": {}, "larger_side": {}}
    if len(left_reps) < 2 or len(right_reps) < 2:
        return {**out, "status": "INSUFFICIENT_DATA", "asymmetry_score": None, "confidence": 0.0,
                "message": "At least two repetitions per side are needed."}

    def mean(rs, attr):
        v = [getattr(r, attr) for r in rs if getattr(r, attr) is not None]
        return float(np.mean(v)) if v else None

    pairs = {
        "rom_proxy": ("amplitude_deg",),
        "gyro_peak": ("peak_velocity_dps",),
        "rep_duration": ("duration_s",),
    }
    values = {}
    for k, (attr,) in pairs.items():
        if attr == "duration_s":
            lv = float(np.mean([r.duration_s for r in left_reps]))
            rv = float(np.mean([r.duration_s for r in right_reps]))
        else:
            lv, rv = mean(left_reps, attr), mean(right_reps, attr)
        out["components"][k] = None if nd(lv, rv) is None else round(nd(lv, rv), 4)
        out["larger_side"][k] = _larger(lv, rv)
        values[k] = {"left": None if lv is None else round(lv, 3),
                     "right": None if rv is None else round(rv, 3)}
    lf = [r.force_peak for r in left_reps if r.force_peak is not None]
    rf = [r.force_peak for r in right_reps if r.force_peak is not None]
    if len(lf) >= 2 and len(rf) >= 2:
        out["components"]["force_peak"] = round(nd(float(np.mean(lf)), float(np.mean(rf))), 4)
        values["force_peak"] = {"left": round(float(np.mean(lf)), 4), "right": round(float(np.mean(rf)), 4)}
    available = [v for v in out["components"].values() if v is not None]
    n = min(len(left_reps), len(right_reps))
    score = float(np.mean(available)) if available else None
    return {**out, "values": values, "status": "OK",
            "asymmetry_score": None if score is None else round(score, 4),
            "confidence": round(min(1.0, n / 8.0), 3), "reps_compared": n}
