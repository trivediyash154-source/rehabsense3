"""RehabSense Movement Quality Index (MQI) — research prototype.

Not validated. Not a clinical score. Every component, its formula and its
weight is listed here and returned with the result, so a reader can see
exactly what the number is made of and disagree with it.

Components (each in [0, 1], higher = more consistent/symmetric/smooth):

    symmetry                1 - bilateral asymmetry score
    rom_proxy_vs_baseline   min(1, session ROM proxy / personal-baseline ROM proxy)
                            (only when a personal baseline exists)
    temporal_consistency    1 - CV of repetition durations
    smoothness              SPARC mapped linearly from [-7, -1.5] to [0, 1]
    force_consistency       1 - CV of per-repetition force peaks
    repetition_consistency  mean pairwise correlation of time-normalised
                            repetition profiles (negative clipped to 0)

Weights: equal across the components that are *available*. This is the
least-assumption choice while there is no labelled data to fit weights
against; WEIGHTS below is where fitted weights will go once therapist quality
labels exist (see the session label table). A component that cannot be
computed is excluded and listed as unavailable, never imputed.

The SPARC mapping bounds are provisional engineering values taken from the
range SPARC typically spans for upper/lower-limb reaching and cyclic movement
in the literature (roughly -7 for very jerky to -1.5 for very smooth); they
are not population norms for this device.

MQI = 100 * sum(w_i * c_i) / sum(w_i) over available components.
"""

from __future__ import annotations

import math

import numpy as np

from app.sensing.repetitions import Rep, coefficient_of_variation, profile_consistency

MQI_VERSION = "mqi-proto-v1"
LABEL = "Movement Quality Index — RESEARCH METRIC — NOT CLINICALLY VALIDATED"
WEIGHTS = {
    "symmetry": 1.0,
    "rom_proxy_vs_baseline": 1.0,
    "temporal_consistency": 1.0,
    "smoothness": 1.0,
    "force_consistency": 1.0,
    "repetition_consistency": 1.0,
}
SPARC_BOUNDS = (-7.0, -1.5)
MIN_REPS = 3
LOW_CONFIDENCE = 0.5

# Expected direction of each component: higher = "more consistent / more
# symmetric / smoother". This is a definitional statement, not a validated
# clinical relationship.
DIRECTIONALITY = {
    "symmetry": "higher when left/right movement is more alike",
    "rom_proxy_vs_baseline": "higher when the range proxy reaches the personal baseline (capped at 1)",
    "temporal_consistency": "higher when repetition durations vary less",
    "smoothness": "higher when SPARC is closer to 0 (fewer speed fluctuations)",
    "force_consistency": "higher when per-repetition force-proxy peaks vary less",
    "repetition_consistency": "higher when repetition shapes correlate more",
}


def definition() -> dict:
    """The frozen definition. Any change alters the hash and needs a new version."""
    return {"version": MQI_VERSION, "weights": WEIGHTS, "sparc_bounds": SPARC_BOUNDS,
            "min_reps": MIN_REPS, "low_confidence": LOW_CONFIDENCE,
            "components": sorted(WEIGHTS), "aggregation": "100 * weighted mean of available components"}


def definition_sha256() -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(definition(), sort_keys=True).encode()).hexdigest()


# Frozen at mqi-proto-v1. tests/test_mqi.py fails if the definition changes
# without a version bump.
FROZEN_DEFINITION_SHA256 = "85c1a046825db92230ab7e0d0724178f610b97978b0d689386f37c9b760eace0"


def _clip01(x: float | None) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return float(max(0.0, min(1.0, x)))


def movement_quality(reps: list[Rep], asymmetry: dict | None, baseline_rom: float | None,
                     stream_quality: float, calibration_quality: float | None) -> dict:
    """Session- or segment-level MQI from completed repetitions."""
    base = {"version": MQI_VERSION, "label": LABEL, "weights": WEIGHTS,
            "sparc_bounds": SPARC_BOUNDS, "definition_sha256": definition_sha256(),
            "validation": "NOT_VALIDATED"}
    if len(reps) < MIN_REPS:
        return {**base, "status": "INSUFFICIENT_DATA", "mqi": None, "confidence": 0.0,
                "components": {}, "unavailable": list(WEIGHTS),
                "message": f"Needs at least {MIN_REPS} repetitions; have {len(reps)}."}

    comps: dict[str, float | None] = {}
    if asymmetry and asymmetry.get("asymmetry_score") is not None:
        comps["symmetry"] = _clip01(1.0 - asymmetry["asymmetry_score"])
    if baseline_rom:
        rom = float(np.mean([r.amplitude_deg for r in reps]))
        comps["rom_proxy_vs_baseline"] = _clip01(rom / baseline_rom)
    cv = coefficient_of_variation([r.duration_s for r in reps])
    comps["temporal_consistency"] = None if cv is None else _clip01(1.0 - cv)
    sp = [r.smoothness_sparc for r in reps if r.smoothness_sparc is not None]
    if sp:
        lo, hi = SPARC_BOUNDS
        comps["smoothness"] = _clip01((float(np.median(sp)) - lo) / (hi - lo))
    fcv = coefficient_of_variation([r.force_peak for r in reps if r.force_peak is not None])
    comps["force_consistency"] = None if fcv is None else _clip01(1.0 - fcv)
    comps["repetition_consistency"] = _clip01(profile_consistency(reps))

    available = {k: v for k, v in comps.items() if v is not None}
    unavailable = [k for k in WEIGHTS if k not in available]
    if not available:
        return {**base, "status": "INSUFFICIENT_DATA", "mqi": None, "confidence": 0.0,
                "components": {}, "unavailable": unavailable}
    wsum = sum(WEIGHTS[k] for k in available)
    mqi = 100.0 * sum(WEIGHTS[k] * v for k, v in available.items()) / wsum

    coverage = len(available) / len(WEIGHTS)
    rep_factor = min(1.0, len(reps) / 8.0)
    cal = 0.6 if calibration_quality is None else 0.4 + 0.6 * calibration_quality
    confidence = coverage ** 0.5 * rep_factor * stream_quality * cal
    status = "OK" if confidence >= LOW_CONFIDENCE else "LOW_CONFIDENCE"
    return {
        **base,
        "status": status,
        "mqi": round(mqi, 1),
        "confidence": round(float(confidence), 3),
        "components": {k: round(v, 4) for k, v in available.items()},
        "unavailable": unavailable,
        # MQIs computed from different component sets are NOT comparable
        # (e.g. without the right IMU there is no symmetry term at all).
        "component_set": sorted(available),
        "reps_used": len(reps),
    }
