"""Unit tests for the signal-processing mathematics."""

from __future__ import annotations

import math

import pytest

from app.processing.filters import butterworth_lowpass
from app.processing.recovery import compute_recovery
from app.processing.confidence import compute_confidence
from app.processing.segmentation import GaitSegmenter, RepetitionSegmenter
from app.processing.signal_processing import LegTracker, inclination_from_accel
from app.processing.symmetry import compute_symmetry
from app.hardware.protocol import SegmentSample
from app.db.models.patient import Leg


# --- filter --------------------------------------------------------------- #

def test_butterworth_is_minus_3db_at_cutoff():
    """The defining property of a Butterworth cutoff."""
    f = butterworth_lowpass(5.0, 100.0)
    assert f.response_db(5.0, 100.0) == pytest.approx(-3.01, abs=0.05)


def test_butterworth_passband_is_maximally_flat():
    f = butterworth_lowpass(5.0, 100.0)
    for freq in (0.1, 0.5, 1.0):
        assert f.response_db(freq, 100.0) == pytest.approx(0.0, abs=0.02)


def test_butterworth_rolls_off_at_12db_per_octave():
    """Second order => 12 dB per octave asymptotically.

    Measured well away from Nyquist: the bilinear transform warps the
    response near fs/2, so a digital Butterworth legitimately falls faster
    than 12 dB/octave up there. That is correct behaviour, not a defect, so
    the asymptote is checked where warping is negligible.
    """
    fs = 20_000.0
    f = butterworth_lowpass(5.0, fs)
    a = f.response_db(40.0, fs)
    b = f.response_db(80.0, fs)
    assert (a - b) == pytest.approx(12.0, abs=0.2)


def test_butterworth_steepens_near_nyquist():
    """Documents the warping above, so the behaviour is pinned deliberately."""
    fs = 400.0
    f = butterworth_lowpass(5.0, fs)
    roll_off = f.response_db(40.0, fs) - f.response_db(80.0, fs)
    assert roll_off > 12.0


def test_filter_does_not_ramp_from_zero():
    """A primed filter starts at the signal, not at 0."""
    f = butterworth_lowpass(5.0, 100.0)
    assert f(9.5) == pytest.approx(9.5, abs=1e-6)


# --- inclination and knee angle ------------------------------------------ #

def test_inclination_matches_atan2_definition():
    s = SegmentSample(ax=math.sin(math.radians(30)), ay=0, az=math.cos(math.radians(30)),
                      gx=0, gy=0, gz=0)
    assert inclination_from_accel(s) == pytest.approx(30.0, abs=0.01)


def test_knee_angle_is_shin_minus_thigh():
    """A static pose: thigh at 10 deg, shin at 55 deg => knee 45 deg."""
    tracker = LegTracker(sample_rate_hz=100.0)

    def seg(theta):
        r = math.radians(theta)
        return SegmentSample(ax=math.sin(r), ay=0.0, az=math.cos(r), gx=0, gy=0, gz=0)

    angle = 0.0
    t = 0.0
    for _ in range(200):
        angle, _ = tracker.update(t, seg(10.0), seg(55.0))
        t += 0.01
    assert angle == pytest.approx(45.0, abs=0.5)


def test_zupt_triggers_on_low_gyro_without_fsr():
    """Gyro-only stance detection is the default path, not a fallback."""
    tracker = LegTracker()
    still = SegmentSample(ax=0, ay=0, az=1, gx=0.1, gy=0.1, gz=0.1)
    moving = SegmentSample(ax=0, ay=0, az=1, gx=90.0, gy=90.0, gz=0.0)
    assert tracker.detect_stance(still, None) is True
    assert tracker.detect_stance(moving, None) is False


def test_fsr_overrides_gyro_for_stance_when_declared():
    tracker = LegTracker(fsr_stance_threshold=0.15)
    moving = SegmentSample(ax=0, ay=0, az=1, gx=90.0, gy=90.0, gz=0.0)
    assert tracker.detect_stance(moving, 0.9) is True
    assert tracker.detect_stance(moving, 0.01) is False


# --- repetitions ---------------------------------------------------------- #

def _drive(segmenter, peak, cycles=3, rate=100.0):
    out = []
    t = 0.0
    for _ in range(cycles):
        for i in range(int(rate)):
            angle = math.pow(math.sin(math.pi * i / rate), 2) * peak
            rep = segmenter.update(t, angle)
            if rep:
                out.append(rep)
            t += 1.0 / rate
    return out


def test_repetition_rom_uses_whole_cycle_not_boundary_sample():
    """The regression this guards: sampling at the boundary reports the trough."""
    seg = RepetitionSegmenter()
    reps = _drive(seg, peak=90.0, cycles=3)
    assert len(reps) >= 2
    for rep in reps:
        assert rep.peak_angle == pytest.approx(90.0, abs=2.0)
        assert rep.rom > 60.0


def test_repetition_rejects_noise_blips():
    seg = RepetitionSegmenter()
    reps = _drive(seg, peak=18.0, cycles=3)  # below min_rom_deg after hysteresis
    assert reps == []


def test_gait_segmenter_derives_cadence():
    gait = GaitSegmenter()
    t, stride = 0.0, 1.0
    for _ in range(8):
        gait.update(t, True)
        gait.update(t + 0.6, False)
        t += stride
    cadence = gait.cadence_spm()
    # One stride per second => 120 steps/min.
    assert cadence == pytest.approx(120.0, abs=5.0)


# --- symmetry ------------------------------------------------------------- #

def test_lsi_is_operated_over_non_operated():
    result = compute_symmetry([80.0], [100.0], Leg.LEFT)
    assert result.lsi_pct == pytest.approx(80.0, abs=0.1)


def test_symmetry_is_none_without_comparable_data_on_both_limbs():
    """A one-limb session has no symmetry; reporting 100% would be a lie."""
    result = compute_symmetry([80.0, 82.0], [], Leg.LEFT)
    assert result.lsi_pct is None
    assert result.comparable_units == 0


def test_symmetry_deviation_formula():
    result = compute_symmetry([90.0], [110.0], Leg.LEFT)
    assert result.deviation_pct == pytest.approx(20.0, abs=0.1)


# --- recovery ------------------------------------------------------------- #

def test_recovery_weights_match_specification():
    result = compute_recovery(rom_deg=100, lsi_pct=90, cadence_spm=100)
    weights = {f.key: f.weight for f in result.factors}
    assert weights == {"rom": 0.30, "symmetry": 0.25, "compliance": 0.20,
                       "cadence": 0.15, "pain": 0.10}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_recovery_is_sum_of_weighted_contributions():
    result = compute_recovery(rom_deg=135, lsi_pct=100, cadence_spm=110,
                              compliance_ratio=1.0, reported_pain=0.0)
    assert result.score == pytest.approx(100.0, abs=0.1)
    assert sum(f.contribution for f in result.factors) == pytest.approx(result.score, abs=0.01)


def test_unavailable_factors_are_flagged_not_hidden():
    result = compute_recovery(rom_deg=100, lsi_pct=None, cadence_spm=None)
    by_key = {f.key: f for f in result.factors}
    assert by_key["symmetry"].available is False
    assert by_key["compliance"].available is False  # neutral default, declared
    assert by_key["pain"].available is False


# --- confidence ----------------------------------------------------------- #

def test_confidence_falls_and_explains_when_one_limb_is_missing():
    full = compute_confidence(
        session_seconds=60, connected_seconds_left=60, connected_seconds_right=60,
        packets_received=600, packets_dropped=0, correction_ratio=0.1,
        calibration_quality=1.0, completed_reps=10,
    )
    partial = compute_confidence(
        session_seconds=60, connected_seconds_left=60, connected_seconds_right=20,
        packets_received=400, packets_dropped=0, correction_ratio=0.1,
        calibration_quality=1.0, completed_reps=10,
    )
    assert partial.value < full.value
    assert "unavailable" in partial.explanation


def test_confidence_bilateral_uses_the_weaker_limb():
    result = compute_confidence(
        session_seconds=100, connected_seconds_left=100, connected_seconds_right=10,
        packets_received=100, packets_dropped=0, correction_ratio=0.0,
        calibration_quality=1.0, completed_reps=8,
    )
    assert result.bilateral_coverage == pytest.approx(0.1, abs=0.01)


# --- packet loss accounting ---------------------------------------------- #

def test_batched_samples_are_not_counted_as_packet_loss():
    """Regression: `seq` is per-sample, so a batch of 10 advances it by 10.

    Comparing packet-to-packet reported 9 losses for every healthy packet,
    which silently suppressed confidence across the whole product.
    """
    from app.hardware.connection_state import LegConnection

    c = LegConnection(leg="LEFT")
    c.connect(device_id="d", firmware="1", protocol=1, capabilities=[], simulated=True, now=0.0)
    seq = 0
    for packet in range(20):
        c.observe_packet(seq, seq + 9, 10, now=float(packet))
        seq += 10
    assert c.packets_received == 20
    assert c.packets_dropped == 0
    assert c.sequence_gaps == 0
    assert c.delivery_ratio == 1.0


def test_a_real_gap_is_still_detected():
    from app.hardware.connection_state import LegConnection

    c = LegConnection(leg="LEFT")
    c.connect(device_id="d", firmware="1", protocol=1, capabilities=[], simulated=True, now=0.0)
    c.observe_packet(0, 9, 10, now=0.0)
    c.observe_packet(30, 39, 10, now=1.0)  # samples 10-29 never arrived
    assert c.sequence_gaps == 1
    assert c.samples_dropped == 20
    assert c.packets_dropped == 2


def test_gait_is_not_penalised_for_expected_zupt_correction():
    """Stance is ~60% of a gait cycle, so ZUPT firing there is by design."""
    gait = compute_confidence(
        session_seconds=60, connected_seconds_left=60, connected_seconds_right=60,
        packets_received=600, packets_dropped=0, correction_ratio=0.60,
        calibration_quality=1.0, completed_reps=20, expected_correction_ratio=0.62,
    )
    reps = compute_confidence(
        session_seconds=60, connected_seconds_left=60, connected_seconds_right=60,
        packets_received=600, packets_dropped=0, correction_ratio=0.60,
        calibration_quality=1.0, completed_reps=20, expected_correction_ratio=0.15,
    )
    assert gait.signal_quality == 1.0
    assert "drift correction" not in gait.explanation
    # The same ratio during a seated exercise is genuinely anomalous.
    assert reps.signal_quality < 1.0
    assert "drift correction" in reps.explanation
