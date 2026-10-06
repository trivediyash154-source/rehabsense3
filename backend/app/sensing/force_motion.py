"""Force / motion relationships.

What the sensors support, and nothing more:

  * When, relative to the movement peak, the force channel peaks.
  * How consistent force peaks are across repetitions.
  * Left/right force difference, *only* if the device declares force
    channels on both sides.
  * Mean force in each movement phase.
  * How strongly force tracks the movement (correlation and its lag).

What it does not do: convert an FSR402 reading to newtons, estimate joint
moments, or interpret "loading strategy". An uncalibrated FSR on a voltage
divider is a monotonic, non-linear, temperature-sensitive load *proxy*; its
unit is reported with every number (`adc_norm` unless a channel declares
otherwise after real calibration).
"""

from __future__ import annotations

import numpy as np

from app.sensing.bilateral import nd
from app.sensing.repetitions import Rep, coefficient_of_variation

FORCE_MOTION_VERSION = "fm-v1"


def _corr_lag(a: np.ndarray, b: np.ndarray, rate: float, max_lag_s: float = 1.0):
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < rate or a.std() < 1e-9 or b.std() < 1e-9:
        return None, None
    a = (a - a.mean()) / a.std()
    b = (b - b.mean()) / b.std()
    full = np.correlate(a, b, mode="full") / len(a)
    lags = np.arange(-len(b) + 1, len(a))
    sel = np.abs(lags) <= int(max_lag_s * rate)
    i = int(np.argmax(np.abs(full[sel])))
    return float(full[sel][i]), float(lags[sel][i] / rate)


def window_force_motion(force: np.ndarray, motion: np.ndarray, rate: float,
                        units: list[str], ids: list[str]) -> dict:
    """Correlation between each force channel and the movement signal.

    `motion` is a per-sample movement magnitude (|w| of the associated side,
    or the mean of both). A positive lag means force follows movement.
    """
    channels = {}
    for j, fid in enumerate(ids):
        f = force[:, j]
        if np.isfinite(f).mean() < 0.9:
            channels[fid] = {"status": "INSUFFICIENT_DATA"}
            continue
        r, lag = _corr_lag(f, motion, rate)
        channels[fid] = {
            "status": "OK" if r is not None else "NO_VARIATION",
            "unit": units[j],
            "mean": round(float(np.nanmean(f)), 4),
            "peak": round(float(np.nanmax(f)), 4),
            "motion_correlation": None if r is None else round(r, 3),
            "lag_s": None if lag is None else round(-lag, 3),
        }
    return {"version": FORCE_MOTION_VERSION, "channels": channels}


def session_force_motion(reps_by_side: dict[str, list[Rep]], force_sides: list[str | None],
                         ids: list[str], units: list[str],
                         phase_force: dict[str, dict[str, float]] | None = None) -> dict:
    """Repetition-level force metrics for the session summary."""
    out = {"version": FORCE_MOTION_VERSION, "unit_note": None, "by_side": {}}
    if not ids:
        return {**out, "status": "NO_FORCE_CHANNELS"}
    out["unit_note"] = (
        "Force channels report a normalised ADC load proxy (adc_norm), not newtons."
        if all(u == "adc_norm" for u in units) else "Units per channel as declared by the device."
    )
    for side, reps in reps_by_side.items():
        peaks = [r.force_peak for r in reps if r.force_peak is not None]
        lags = [r.force_peak_lag_s for r in reps if r.force_peak_lag_s is not None]
        if not peaks:
            continue
        cv = coefficient_of_variation(peaks)
        out["by_side"][side] = {
            "reps_with_force": len(peaks),
            "force_peak_mean": round(float(np.mean(peaks)), 4),
            "force_peak_cv": None if cv is None else round(cv, 4),
            "force_consistency": None if cv is None else round(max(0.0, 1.0 - cv), 4),
            "force_peak_lag_s_mean": round(float(np.mean(lags)), 3) if lags else None,
            "description": (
                "Force peak occurs on average "
                f"{abs(float(np.mean(lags))):.2f} s {'after' if np.mean(lags) >= 0 else 'before'} "
                "the movement peak." if lags else None
            ),
        }
    sides_with_force = {s for s in force_sides if s in ("LEFT", "RIGHT")}
    if sides_with_force == {"LEFT", "RIGHT"} and {"LEFT", "RIGHT"} <= set(out["by_side"]):
        lv = out["by_side"]["LEFT"]["force_peak_mean"]
        rv = out["by_side"]["RIGHT"]["force_peak_mean"]
        out["force_symmetry"] = {"normalised_difference": round(nd(lv, rv), 4),
                                 "left": lv, "right": rv}
    else:
        out["force_symmetry"] = None
        out["force_symmetry_note"] = (
            "Force symmetry needs force channels declared on both LEFT and RIGHT."
        )
    if phase_force:
        out["force_by_phase"] = phase_force
    out["status"] = "OK" if out["by_side"] else "INSUFFICIENT_DATA"
    return out


def force_by_phase(t: np.ndarray, force: np.ndarray, reps: list[Rep]) -> dict[str, float]:
    """Mean force in each movement phase, pooled across repetitions."""
    pooled: dict[str, list[float]] = {}
    for r in reps:
        for phase, a, b in r.phase_segments or []:
            m = (t >= a) & (t < b)
            vals = force[m]
            vals = vals[np.isfinite(vals)]
            if len(vals):
                pooled.setdefault(phase, []).extend(vals.tolist())
    return {p: round(float(np.mean(v)), 4) for p, v in pooled.items() if v}
