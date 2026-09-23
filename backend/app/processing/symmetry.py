"""Bilateral symmetry.

    LSI = X_operated / X_non_operated * 100%
    deviation = |X_left - X_right| / (0.5 * (X_left + X_right)) * 100%

X must be a *comparable* parameter — peak repetition ROM, peak angular
velocity, or stance time. Instantaneous knee angles are never comparable
between limbs, because the limbs are phase-shifted: at any single instant one
is flexing while the other extends, so their ratio says nothing about
symmetry. Only aggregates over completed cycles are used here.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.models.patient import Leg


@dataclass
class SymmetryResult:
    lsi_pct: float | None
    deviation_pct: float | None
    parameter: str
    left_value: float | None
    right_value: float | None
    operated_leg: Leg | None
    comparable_units: int

    def as_dict(self) -> dict:
        return {
            "lsi_pct": self.lsi_pct,
            "deviation_pct": self.deviation_pct,
            "parameter": self.parameter,
            "left_value": self.left_value,
            "right_value": self.right_value,
            "operated_leg": self.operated_leg.value if self.operated_leg else None,
            "comparable_units": self.comparable_units,
        }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def compute_symmetry(
    left_values: list[float],
    right_values: list[float],
    operated_leg: Leg | None,
    parameter: str = "peak_rom",
    min_units: int = 1,
) -> SymmetryResult:
    """Symmetry over comparable per-limb aggregates.

    Returns `None` values rather than a fabricated number when either limb has
    no comparable data — a one-limb session has no symmetry, and saying so is
    more useful than reporting 100%.
    """
    comparable = min(len(left_values), len(right_values))
    left = _mean(left_values)
    right = _mean(right_values)

    if comparable < min_units or not left or not right or left <= 0 or right <= 0:
        return SymmetryResult(
            lsi_pct=None,
            deviation_pct=None,
            parameter=parameter,
            left_value=left,
            right_value=right,
            operated_leg=operated_leg,
            comparable_units=comparable,
        )

    if operated_leg is Leg.LEFT:
        operated, non_operated = left, right
    elif operated_leg is Leg.RIGHT:
        operated, non_operated = right, left
    else:
        # Without a designated operated limb, report the conservative ratio.
        operated, non_operated = min(left, right), max(left, right)

    lsi = (operated / non_operated) * 100.0
    deviation = abs(left - right) / (0.5 * (left + right)) * 100.0

    return SymmetryResult(
        lsi_pct=round(lsi, 1),
        deviation_pct=round(deviation, 1),
        parameter=parameter,
        left_value=round(left, 2),
        right_value=round(right, 2),
        operated_leg=operated_leg,
        comparable_units=comparable,
    )
