"""Confidence as a first-class, explainable quantity.

Derived from data coverage, bilateral availability, repetition coverage,
signal quality and how much ZUPT/filter correction was needed — and returned
with a plain-language explanation, so the interface can say *why* confidence
is low rather than only showing a percentage.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceResult:
    value: float
    coverage: float
    bilateral_coverage: float
    signal_quality: float
    calibration_quality: float
    repetition_coverage: float
    explanation: str
    band: str

    def as_dict(self) -> dict:
        return {
            "value": round(self.value, 3),
            "percent": round(self.value * 100, 1),
            "band": self.band,
            "coverage": round(self.coverage, 3),
            "bilateral_coverage": round(self.bilateral_coverage, 3),
            "signal_quality": round(self.signal_quality, 3),
            "calibration_quality": round(self.calibration_quality, 3),
            "repetition_coverage": round(self.repetition_coverage, 3),
            "explanation": self.explanation,
        }


def _band(value: float) -> str:
    if value >= 0.75:
        return "Higher"
    if value >= 0.5:
        return "Moderate"
    return "Lower"


def compute_confidence(
    *,
    session_seconds: float,
    connected_seconds_left: float,
    connected_seconds_right: float,
    packets_received: int,
    packets_dropped: int,
    correction_ratio: float,
    calibration_quality: float | None,
    completed_reps: int,
    expected_reps: int | None = None,
    expected_correction_ratio: float = 0.15,
) -> ConfidenceResult:
    """
    `expected_correction_ratio` is how much ZUPT correction is *normal* for
    the movement. During gait, stance occupies roughly 60% of every cycle and
    ZUPT firing there is the designed behaviour, not a fault — penalising it
    would tell every walking session its confidence was reduced. Only
    correction beyond what the movement implies counts against quality.
    """
    span = max(session_seconds, 1e-6)

    left_cov = min(1.0, connected_seconds_left / span)
    right_cov = min(1.0, connected_seconds_right / span)
    coverage = (left_cov + right_cov) / 2.0
    # Bilateral coverage is the *weaker* limb: a session is only as bilateral
    # as its worst side, so averaging would flatter a one-sided recording.
    bilateral = min(left_cov, right_cov)

    total_packets = packets_received + packets_dropped
    delivery = 1.0 if total_packets == 0 else packets_received / total_packets
    # Correction beyond what this movement normally produces means the
    # estimate leaned on gravity rather than tracking cleanly.
    excess_correction = max(0.0, correction_ratio - expected_correction_ratio)
    signal_quality = max(0.0, min(1.0, delivery * (1.0 - 0.7 * excess_correction)))

    calib = 0.5 if calibration_quality is None else max(0.0, min(1.0, calibration_quality))

    if expected_reps and expected_reps > 0:
        rep_cov = min(1.0, completed_reps / expected_reps)
    else:
        # Without a target, a handful of reps is enough to be interpretable.
        rep_cov = min(1.0, completed_reps / 8.0) if completed_reps else 0.0

    value = (
        0.30 * coverage
        + 0.25 * bilateral
        + 0.20 * signal_quality
        + 0.15 * calib
        + 0.10 * rep_cov
    )
    value = max(0.0, min(1.0, value))

    reasons: list[str] = []
    if bilateral < 0.7:
        weaker = "right" if right_cov < left_cov else "left"
        reasons.append(
            f"the {weaker} limb was unavailable for part of the session "
            f"({min(left_cov, right_cov) * 100:.0f}% bilateral coverage)"
        )
    if delivery < 0.95 and total_packets:
        reasons.append(f"{packets_dropped} packets were dropped or arrived out of order")
    if excess_correction > 0.25:
        reasons.append(
            "the orientation estimate needed more drift correction than this movement implies"
        )
    if calibration_quality is not None and calibration_quality < 0.5:
        reasons.append("the limb was not fully still during the calibration window")
    if rep_cov < 0.5:
        reasons.append(f"only {completed_reps} repetitions were segmented")

    if reasons:
        explanation = "Confidence is reduced because " + "; ".join(reasons) + "."
    else:
        explanation = (
            "Both limbs reported throughout, packet delivery was complete and calibration "
            "was clean, so these estimates are as dependable as this prototype produces."
        )

    return ConfidenceResult(
        value=value,
        coverage=coverage,
        bilateral_coverage=bilateral,
        signal_quality=signal_quality,
        calibration_quality=calib,
        repetition_coverage=rep_cov,
        explanation=explanation,
        band=_band(value),
    )
