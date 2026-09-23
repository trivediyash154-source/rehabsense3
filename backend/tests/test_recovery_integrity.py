"""The recovery indicator must describe measured movement, or nothing at all.

Compliance and pain fall back to neutral defaults when they are absent. Those
two alone carry 0.20 + 0.10 of the weighting, so a naive sum reports 30/100 for
a session in which no limb was ever measured -- a confident-looking number
about nothing. These tests pin the rule that prevents it.
"""

from __future__ import annotations

import pytest

from app.processing.recovery import compute_recovery


def test_a_session_with_no_measurements_is_not_scored() -> None:
    result = compute_recovery(
        rom_deg=None, lsi_pct=None, cadence_spm=None, reported_pain=None,
    )
    assert result.score is None
    assert result.scored is False
    payload = result.as_dict()
    assert payload["value"] is None
    assert "no recovery indicator was calculated" in payload["unscored_reason"]


def test_the_neutral_defaults_alone_never_become_a_score() -> None:
    """Specifically guards the 30/100 case."""
    result = compute_recovery(
        rom_deg=None, lsi_pct=None, cadence_spm=None, reported_pain=3,
    )
    assert result.score is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rom_deg": 64.0},
        {"lsi_pct": 94.0},
        {"cadence_spm": 102.0},
    ],
)
def test_one_real_measurement_is_enough_to_score(kwargs) -> None:
    base = {"rom_deg": None, "lsi_pct": None, "cadence_spm": None, "reported_pain": None}
    result = compute_recovery(**{**base, **kwargs})
    assert result.score is not None
    assert 0.0 <= result.score <= 100.0


def test_unavailable_factors_are_still_reported_as_unavailable() -> None:
    """The breakdown must show what was missing, not silently omit it."""
    result = compute_recovery(
        rom_deg=64.0, lsi_pct=None, cadence_spm=None, reported_pain=None,
    )
    by_key = {f.key: f for f in result.factors}
    assert by_key["rom"].available is True
    assert by_key["symmetry"].available is False
    assert by_key["pain"].available is False


def test_contributions_sum_to_the_reported_score() -> None:
    result = compute_recovery(
        rom_deg=64.0, lsi_pct=94.0, cadence_spm=102.0, reported_pain=2,
    )
    total = sum(f.contribution for f in result.factors)
    assert result.score == pytest.approx(total, abs=1e-9)
