"""The explainable composite recovery score.

    R = sum(w_i * s_i) for i in {rom, symmetry, compliance, cadence, pain}

with the documented default weights. The engine returns not just R but every
normalised factor and its weighted contribution — that decomposition *is* the
"explainable" part, and the frontend renders it rather than recomputing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings


@dataclass
class Factor:
    key: str
    label: str
    weight: float
    # Normalised 0..1, or None when the input genuinely is not available.
    normalized: float | None
    contribution: float
    available: bool
    note: str

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "weight": round(self.weight, 3),
            "normalized": None if self.normalized is None else round(self.normalized, 4),
            "value": None if self.normalized is None else round(self.normalized * 100, 1),
            "contribution": round(self.contribution, 2),
            "available": self.available,
            "note": self.note,
        }


@dataclass
class RecoveryResult:
    # None when nothing about the movement was actually measured. A score is
    # an estimate derived from data; with no data there is no estimate, and
    # emitting one anyway would be a number about nothing.
    score: float | None
    factors: list[Factor] = field(default_factory=list)
    analytics_version: str = "mvp-1.0"

    @property
    def scored(self) -> bool:
        return self.score is not None

    def as_dict(self) -> dict:
        return {
            "value": None if self.score is None else round(self.score, 1),
            "scale": "0-100",
            "analytics_version": self.analytics_version,
            "contributions": [f.as_dict() for f in self.factors],
            "unscored_reason": (
                None
                if self.score is not None
                else (
                    "No range of motion, symmetry or cadence could be measured in "
                    "this session, so no recovery indicator was calculated."
                )
            ),
            "disclaimer": (
                "Estimated decision-support indicator. Not a diagnosis, prognosis, "
                "clearance criterion or clinical measurement."
            ),
        }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_recovery(
    *,
    rom_deg: float | None,
    lsi_pct: float | None,
    cadence_spm: float | None,
    compliance_ratio: float | None = None,
    reported_pain: float | None = None,
) -> RecoveryResult:
    """Compute the weighted composite score.

    Unavailable inputs fall back to their documented neutral defaults
    (compliance and pain default to 1.0 until those modules exist) and are
    marked `available: false` so the interface can say so rather than implying
    the factor was measured.
    """
    settings = get_settings()
    w = settings.weights
    factors: list[Factor] = []

    # --- ROM against a configurable target for the exercise/stage ---
    if rom_deg is None:
        rom_norm, rom_available, rom_note = 0.0, False, "No repetition or gait cycle completed."
    else:
        rom_norm = _clamp01(rom_deg / settings.target_rom_deg)
        rom_available = True
        rom_note = f"Peak estimated ROM {rom_deg:.0f}° against a {settings.target_rom_deg:.0f}° reference."
    factors.append(Factor("rom", "Range of motion", w["rom"], rom_norm, rom_norm * w["rom"] * 100, rom_available, rom_note))

    # --- symmetry: LSI proximity to 100% ---
    if lsi_pct is None:
        sym_norm, sym_available = 0.0, False
        sym_note = "Both limbs did not produce comparable cycles, so symmetry is undefined."
    else:
        sym_norm = _clamp01(lsi_pct / 100.0)
        sym_available = True
        sym_note = f"Limb Symmetry Index {lsi_pct:.0f}% of the non-operated limb."
    factors.append(Factor("symmetry", "Bilateral symmetry", w["symmetry"], sym_norm, sym_norm * w["symmetry"] * 100, sym_available, sym_note))

    # --- compliance: neutral until a prescription module exists ---
    if compliance_ratio is None:
        comp_norm, comp_available = 1.0, False
        comp_note = "Neutral default: no prescribed schedule is connected."
    else:
        comp_norm = _clamp01(compliance_ratio)
        comp_available = True
        comp_note = f"{comp_norm * 100:.0f}% of prescribed sessions completed."
    factors.append(Factor("compliance", "Exercise compliance", w["compliance"], comp_norm, comp_norm * w["compliance"] * 100, comp_available, comp_note))

    # --- cadence against a healthy reference ---
    if cadence_spm is None:
        cad_norm, cad_available = 0.0, False
        cad_note = "Cadence is only derived for gait-type exercises with detected strides."
    else:
        cad_norm = _clamp01(cadence_spm / settings.reference_cadence_spm)
        cad_available = True
        cad_note = f"Cadence {cadence_spm:.0f} steps/min against a {settings.reference_cadence_spm:.0f} reference."
    factors.append(Factor("cadence", "Cadence", w["cadence"], cad_norm, cad_norm * w["cadence"] * 100, cad_available, cad_note))

    # --- inverse pain ---
    if reported_pain is None:
        pain_norm, pain_available = 1.0, False
        pain_note = "Neutral default: no patient-reported pain was recorded."
    else:
        pain_norm = _clamp01(1.0 - (reported_pain / 10.0))
        pain_available = True
        pain_note = f"Reported pain {reported_pain:.0f}/10."
    factors.append(Factor("pain", "Inverse pain factor", w["pain"], pain_norm, pain_norm * w["pain"] * 100, pain_available, pain_note))

    # The composite is only meaningful if something was actually measured.
    # Compliance and pain fall back to neutral defaults when absent, and those
    # alone sum to a non-zero score -- which would present a session that
    # recorded nothing as though it had a real indicator.
    measured = {"rom", "symmetry", "cadence"}
    if not any(f.key in measured and f.available for f in factors):
        return RecoveryResult(
            score=None, factors=factors, analytics_version=settings.analytics_version
        )

    score = sum(f.contribution for f in factors)
    return RecoveryResult(score=score, factors=factors, analytics_version=settings.analytics_version)
