"""Change from personal baseline.

A patient's own earlier sessions are the reference, not a population norm
the device has never been validated against. The output is deliberately
plain: baseline value, current value, absolute and relative change, and a
direction word. It is never phrased as improvement, deterioration or
recovery, because nothing here has been clinically validated to mean that.
"""

from __future__ import annotations

import math

BASELINE_VERSION = "baseline-v1"
LABEL = "Change from personal baseline"

# Metrics a baseline can hold, with the unit shown to the user.
METRICS = {
    "asymmetry_score": "0-1 (0 = identical sides)",
    "mqi": "MQI points (research prototype)",
    "rom_proxy_deg_left": "deg (segment tilt range, proxy)",
    "rom_proxy_deg_right": "deg (segment tilt range, proxy)",
    "rep_duration_s": "s",
    "peak_velocity_dps_left": "deg/s",
    "peak_velocity_dps_right": "deg/s",
    "force_peak_mean": "force channel unit",
}
# Relative changes smaller than this are reported as "similar".
SIMILAR_BAND = 0.05


def compare(current: dict, baseline: dict) -> dict:
    rows = {}
    notes = []
    for key, unit in METRICS.items():
        if key == "mqi" and current.get("mqi_component_set") != baseline.get("mqi_component_set") \
                and current.get("mqi_component_set") is not None and baseline.get("mqi_component_set") is not None:
            notes.append("MQI not compared: computed from different component sets "
                         f"({baseline.get('mqi_component_set')} vs {current.get('mqi_component_set')}).")
            continue
        b, c = baseline.get(key), current.get(key)
        if b is None or c is None or not (math.isfinite(b) and math.isfinite(c)):
            continue
        diff = c - b
        rel = None if abs(b) < 1e-6 else diff / abs(b)
        if rel is not None:
            direction = "similar" if abs(rel) < SIMILAR_BAND else ("higher" if diff > 0 else "lower")
        else:
            direction = "similar" if abs(diff) < 1e-6 else ("higher" if diff > 0 else "lower")
        rows[key] = {
            "baseline": round(b, 4),
            "current": round(c, 4),
            "change": round(diff, 4),
            "change_pct": None if rel is None else round(100.0 * rel, 1),
            "direction": direction,
            "unit": unit,
        }
    return {
        "version": BASELINE_VERSION,
        "label": LABEL,
        "metrics": rows,
        "note": (
            "Compared with this patient's own baseline session(s). A change is a "
            "difference in a measured indicator, not a clinical judgement."
        ),
        "not_compared": notes,
    }


def baseline_metrics_from_summary(summary: dict) -> dict:
    """Pull the comparable numbers out of a finalised v2 session summary."""
    out: dict = {}
    asym = summary.get("bilateral") or {}
    if asym.get("asymmetry_score") is not None:
        out["asymmetry_score"] = asym["asymmetry_score"]
    mqi = summary.get("movement_quality") or {}
    if mqi.get("mqi") is not None:
        out["mqi"] = mqi["mqi"]
        out["mqi_component_set"] = mqi.get("component_set")
    per_side = summary.get("repetition_summary") or {}   # v2: "repetitions" is a count
    for side in ("LEFT", "RIGHT"):
        agg = per_side.get(side) or {}
        if agg.get("rom_proxy_deg_mean") is not None:
            out[f"rom_proxy_deg_{side.lower()}"] = agg["rom_proxy_deg_mean"]
        if agg.get("peak_velocity_dps_mean") is not None:
            out[f"peak_velocity_dps_{side.lower()}"] = agg["peak_velocity_dps_mean"]
    durations = [(per_side.get(s) or {}).get("duration_s_mean") for s in ("LEFT", "RIGHT")]
    durations = [d for d in durations if d is not None]
    if durations:
        out["rep_duration_s"] = sum(durations) / len(durations)
    fm = summary.get("force_motion") or {}
    peaks = [v.get("force_peak_mean") for v in (fm.get("by_side") or {}).values()
             if v.get("force_peak_mean") is not None]
    if peaks:
        out["force_peak_mean"] = sum(peaks) / len(peaks)
    return out


def average_metrics(items: list[dict]) -> dict:
    keys = {k for d in items for k in d}
    out = {}
    sets = {tuple(d.get("mqi_component_set") or ()) for d in items if "mqi" in d}
    if len(sets) > 1:
        keys -= {"mqi", "mqi_component_set"}      # incomparable MQIs are not averaged
    elif sets:
        out["mqi_component_set"] = list(next(iter(sets)))
        keys.discard("mqi_component_set")
    for k in keys:
        vals = [d[k] for d in items if d.get(k) is not None]
        if vals:
            out[k] = sum(vals) / len(vals)
    return out
