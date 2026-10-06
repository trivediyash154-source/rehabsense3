"""Unit tests for the hardware-v2 sensing stages.

Each stage is tested against a known ground truth (the simulator's
physically-consistent kinematics, or constructed signals), not against
"it returned something".
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from app.hardware.protocol_v2 import DualSample, HelloV2
from app.sensing import features as F
from app.sensing.baseline import compare
from app.sensing.bilateral import window_asymmetry
from app.sensing.calibration import DeviceCalibrator
from app.sensing.channels import ChannelLayout, samples_to_array
from app.sensing.inference import BundleError, ModelBundle, classify_window, sha256_file
from app.sensing.orientation import TiltEstimator, principal_axis, unit
from app.sensing.quality import movement_quality
from app.sensing.repetitions import BilateralMode, RepMode, detect_reps, sparc
from app.sensing.stream import StreamMonitor
from app.sensing.windowing import PREPROCESSING_VERSION, SlidingWindowBuffer, resample_uniform
from app.simulator.dual_imu import DualImuModel, SideConfig, random_rotation


def hello(force=2, right=True, rate=100.0, simulated=True) -> HelloV2:
    imus = [{"side": "LEFT", "placement": "SHANK"}]
    if right:
        imus.append({"side": "RIGHT", "placement": "SHANK"})
    fc = [{"id": f"f{i}", "side": ["LEFT", "RIGHT"][i % 2]} for i in range(force)]
    return HelloV2(protocol_version=2, device_id="test-dev", sample_rate_hz=rate, imus=imus,
                   force_channels=fc, simulated=simulated)


def stream(model: DualImuModel, seconds: float, rate=100.0):
    samples = [DualSample(ts=i / rate, seq=i, **model.sample(i / rate))
               for i in range(int(seconds * rate))]
    return samples


# ------------------------------------------------------------------ #
# protocol
# ------------------------------------------------------------------ #

def test_protocol_rejects_v1_version_and_duplicate_sides():
    with pytest.raises(ValueError):
        HelloV2(protocol_version=1, device_id="x", sample_rate_hz=100,
                imus=[{"side": "LEFT"}])
    with pytest.raises(ValueError):
        HelloV2(protocol_version=2, device_id="x", sample_rate_hz=100,
                imus=[{"side": "LEFT"}, {"side": "LEFT"}])
    with pytest.raises(ValueError):
        HelloV2(protocol_version=2, device_id="x", sample_rate_hz=5000, imus=[{"side": "LEFT"}])


def test_force_channel_count_is_configurable_and_missing_is_nan():
    for n in (0, 1, 3):
        layout = ChannelLayout.from_hello(hello(force=n))
        assert layout.n_channels == 12 + n
    layout = ChannelLayout.from_hello(hello(force=2))
    s = DualSample(ts=0.0, seq=0, imu_left={"ax": 0, "ay": 0, "az": 1, "gx": 0, "gy": 0, "gz": 0},
                   imu_right=None, force=[0.5, None])
    _, _, data = samples_to_array([s], layout)
    assert data[0, 2] == 1.0
    assert np.isnan(data[0, 6:12]).all(), "a missing IMU must be NaN, never zero"
    assert data[0, 12] == 0.5 and np.isnan(data[0, 13])


# ------------------------------------------------------------------ #
# stream integrity
# ------------------------------------------------------------------ #

def _block(seqs, ts):
    data = np.ones((len(seqs), 12))
    return np.asarray(ts, float), np.asarray(seqs), data


def test_stream_monitor_drops_duplicates_and_out_of_order_and_counts_gaps():
    m = StreamMonitor(declared_rate_hz=100)
    keep = m.observe(*_block([0, 1, 2], [0.00, 0.01, 0.02]), arrival=10.0)
    assert keep.all()
    keep = m.observe(*_block([2, 3], [0.02, 0.03]), arrival=10.1)      # duplicate of 2
    assert keep.tolist() == [False, True] and m.duplicates == 1
    keep = m.observe(*_block([1], [0.01]), arrival=10.2)               # retransmit of 1
    assert not keep.any() and m.duplicates == 2
    keep = m.observe(*_block([7, 8], [0.07, 0.08]), arrival=10.3)      # 4, 5, 6 missing
    assert keep.all() and m.gaps == 1 and m.missing_samples == 3
    keep = m.observe(*_block([5], [0.05]), arrival=10.4)               # 5 arrives late
    assert not keep.any() and m.out_of_order == 1


def test_stream_monitor_measures_rate_and_clock_drift():
    m = StreamMonitor(declared_rate_hz=100)
    drift = 1.0 + 500e-6   # device clock 500 ppm fast relative to server
    seq = 0
    for k in range(600):   # 60 s of 10-sample packets
        ts = np.array([(seq + i) / 100.0 * drift for i in range(10)])
        arrival = 1000.0 + (seq + 9) / 100.0 + 0.005
        m.observe(ts, np.arange(seq, seq + 10), np.ones((10, 12)), arrival)
        seq += 10
    assert m.measured_rate_hz == pytest.approx(100 / drift, rel=1e-3)
    # arrival advances 1/drift per device second -> about -500 ppm
    assert m.clock_drift_ppm == pytest.approx(-500, abs=30)


def test_stream_monitor_flags_frozen_imu():
    m = StreamMonitor(declared_rate_hz=100)
    data = np.ones((40, 12))
    data[:, 6:12] = np.random.default_rng(0).normal(size=(40, 6))
    m.observe(np.arange(40) / 100, np.arange(40), data, arrival=1.0)
    assert m.frozen_flags["LEFT"] and not m.frozen_flags["RIGHT"]


# ------------------------------------------------------------------ #
# calibration and orientation
# ------------------------------------------------------------------ #

def _calibrate(model, h, seconds=12.0):
    # health check (1 s) + detected still period (3 s) + movement (5 s) +
    # margin; the model holds still for model.still_s before moving.
    layout = ChannelLayout.from_hello(h)
    cal = DeviceCalibrator(layout, h.sample_rate_hz, still_seconds=3.0, movement_seconds=5.0)
    ts, _, data = samples_to_array(stream(model, seconds), layout)
    cal.observe(ts, data, 100.0)
    return cal, layout


def test_calibration_passes_on_good_sensors_with_arbitrary_mounting():
    cal, _ = _calibrate(DualImuModel(exercise="SQUAT", seed=3), hello())
    checks = {c.key: c.status.value for c in cal.checks}
    assert cal.complete and cal.phase.value == "COMPLETE"
    assert len(checks) == 8
    assert all(v == "PASS" for v in checks.values()), checks
    meta = json.loads(json.dumps(cal.metadata()))   # must be JSON-serialisable
    assert meta["sampling_rate"]["declared_hz"] == 100
    assert {"left_imu_offset", "right_imu_offset", "force_offset", "orientation"} <= set(meta)


def test_calibration_recovers_per_sensor_gyro_bias():
    model = DualImuModel(exercise="SQUAT", seed=11)
    cal, _ = _calibrate(model, hello())
    for side in ("LEFT", "RIGHT"):
        assert np.allclose(cal.sides[side].gyro_bias, model.gyro_bias[side], atol=0.15)


def test_calibration_fails_missing_right_imu_but_keeps_left():
    model = DualImuModel(exercise="SQUAT", right=SideConfig(present=False))
    cal, _ = _calibrate(model, hello(right=True))
    conn = next(c for c in cal.checks if c.key == "imu_connectivity")
    assert conn.status.value == "FAIL" and conn.detail["RIGHT"] == "FAIL"
    assert cal.sides["LEFT"].usable and not cal.sides["RIGHT"].usable
    assert cal.phase.value == "COMPLETE"


def test_calibration_flags_saturated_force_channel():
    model = DualImuModel(exercise="SQUAT")
    h = hello(force=1)
    layout = ChannelLayout.from_hello(h)
    cal = DeviceCalibrator(layout, 100.0)
    ts, _, data = samples_to_array(stream(model, 12.0), layout)
    data[:, 12] = 1.0
    cal.observe(ts, data, 100.0)
    force = next(c for c in cal.checks if c.key == "force_sensor")
    assert force.status.value == "FAIL"


def test_tilt_tracks_ground_truth_under_random_mounting():
    """The tilt estimator must recover the simulated segment angle regardless
    of how the IMU was strapped on."""
    model = DualImuModel(exercise="SQUAT", seed=21)
    cal, layout = _calibrate(model, hello())
    est = TiltEstimator(100.0)
    est.configure(cal.sides["LEFT"].g0, cal.sides["LEFT"].axis)
    samples = stream(model, 30.0)
    ts, _, data = samples_to_array(samples, layout)
    corrected = cal.apply(data)
    errs = []
    move_end = model.still_s + model.calib_move_s     # simulator's slowed calibration movement
    for i in range(int(move_end * 100), len(ts)):
        v = est.update(corrected[i, 0:3], corrected[i, 3:6], 0.01)
        # Simulator time mapping after its calibration movement (see DualImuModel.sample).
        truth = model.tilt("LEFT", ts[i] - move_end + 0.6 * model.calib_move_s)
        if ts[i] > move_end + 3.0:
            errs.append(abs(abs(v) - abs(truth)))
    assert np.median(errs) < 2.5, np.median(errs)


def test_principal_axis_is_none_when_still():
    assert principal_axis(np.random.default_rng(0).normal(0, 0.3, (300, 3))) is None


# ------------------------------------------------------------------ #
# windowing and features
# ------------------------------------------------------------------ #

def test_resample_bridges_gaps_and_keeps_shape():
    ts = np.array([0.0, 0.01, 0.03, 0.04])
    data = np.array([[0.0], [1.0], [3.0], [4.0]])
    out = resample_uniform(ts, data, 100.0)
    assert out.shape == (5, 1) and out[2, 0] == pytest.approx(2.0)


def test_sliding_window_emits_on_stride():
    buf = SlidingWindowBuffer(window_s=2.0, stride_s=0.5, n_channels=1)
    t = np.arange(0, 5.0, 0.01)
    buf.extend(t, t[:, None])
    wins = buf.pop_windows()
    assert [round(w[1], 2) for w in wins] == [2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
    assert buf.pop_windows() == []


def test_invariant_features_do_not_change_when_the_sensor_is_rotated():
    rng = np.random.default_rng(5)
    model = DualImuModel(exercise="WALK", seed=5)
    samples = stream(model, 12.0)
    layout = ChannelLayout.from_hello(hello())
    _, _, data = samples_to_array(samples, layout)
    left = data[900:1100, 0:6][None]
    rot = random_rotation(rng)
    rotated = left.copy()
    rotated[..., 0:3] = left[..., 0:3] @ rot.T
    rotated[..., 3:6] = left[..., 3:6] @ rot.T
    # The neutral pose is measured in each sensor's own frame, so it rotates
    # with the sensor.
    g0 = np.array([0.0, 0.0, 1.0])
    a = F.side_features(left, 100.0, g0)
    b = F.side_features(rotated, 100.0, rot @ g0)
    assert np.allclose(a, b, rtol=1e-6, atol=1e-6)
    raw_a = F.raw_axis_features(left, 100.0)
    raw_b = F.raw_axis_features(rotated, 100.0)
    assert not np.allclose(raw_a, raw_b), "raw-axis features should change; that is the point"


def test_feature_name_count_matches_vector():
    g0 = np.array([0.0, 0.0, 1.0])
    x = F.bilateral_features(np.random.rand(2, 50, 6), np.random.rand(2, 50, 6), 25.0, g0, g0)
    assert x.shape == (2, len(F.bilateral_feature_names()))


# ------------------------------------------------------------------ #
# bilateral, reps, quality, baseline
# ------------------------------------------------------------------ #

def _sim_window(severity_left: float, exercise="SQUAT"):
    model = DualImuModel(exercise=exercise, seed=9, left=SideConfig(severity=severity_left))
    layout = ChannelLayout.from_hello(hello())
    cal, _ = _calibrate(model, hello())
    ts, _, data = samples_to_array(stream(model, 30.0), layout)
    corrected = cal.apply(data)[1500:2500]   # 15-25 s: well after calibration
    return corrected


def test_bilateral_near_zero_for_identical_sides_and_grows_with_asymmetry():
    sym = _sim_window(0.0)
    asym = _sim_window(0.5)
    avail = {"LEFT": 1.0, "RIGHT": 1.0}
    s0 = window_asymmetry(sym[:, 0:6], sym[:, 6:12], None, None, 100.0,
                          BilateralMode.SYNCHRONOUS, avail)
    s1 = window_asymmetry(asym[:, 0:6], asym[:, 6:12], None, None, 100.0,
                          BilateralMode.SYNCHRONOUS, avail)
    assert s0["status"] == "OK" and s0["asymmetry_score"] < 0.05
    # Separation, not an absolute value: the score averages components that a
    # pure range reduction does not move (waveform shape, timing).
    assert s1["asymmetry_score"] > 0.1 and s1["asymmetry_score"] > 5 * s0["asymmetry_score"]
    assert s1["larger_side"]["gyro_rms"] == "RIGHT"


def test_bilateral_refuses_single_side():
    sym = _sim_window(0.0)
    out = window_asymmetry(sym[:, 0:6], sym[:, 6:12], None, None, 100.0,
                           BilateralMode.SYNCHRONOUS, {"LEFT": 1.0, "RIGHT": 0.0})
    assert out["status"] == "SINGLE_SIDE" and out["asymmetry_score"] is None


def test_rep_detection_counts_constructed_repetitions():
    rate = 50.0
    t = np.arange(0, 30, 1 / rate)
    tilt = 40 * np.sin(np.pi * t / 3.0) ** 2   # one rep per 3 s
    w = np.gradient(tilt, t)
    reps = detect_reps("LEFT", t, tilt, w, rate, RepMode.REPETITION)
    assert len(reps) in (9, 10)
    assert all(abs(r.amplitude_deg - 40) < 1.5 for r in reps)
    # A rep runs from leaving to returning within 5% of the trough level, so
    # a rest-free sin^2 cycle of 3 s spans 3 - 2*(3/pi)*asin(sqrt(.05)) s.
    expected = 3.0 - 2 * (3.0 / math.pi) * math.asin(math.sqrt(0.05))
    assert all(abs(r.duration_s - expected) < 0.05 for r in reps)
    assert detect_reps("LEFT", t, tilt, w, rate, RepMode.NONE) == []


def test_sparc_smooth_beats_jerky():
    t = np.linspace(0, 1, 100)
    smooth = np.sin(np.pi * t) ** 2
    jerky = smooth + 0.15 * np.sin(2 * np.pi * 9 * t) ** 2
    assert sparc(smooth, 100) > sparc(jerky, 100)


def test_quality_needs_reps_and_never_imputes():
    out = movement_quality([], None, None, 1.0, 1.0)
    assert out["status"] == "INSUFFICIENT_DATA" and out["mqi"] is None


def test_baseline_comparison_language_and_zero_baseline():
    out = compare({"asymmetry_score": 0.16, "mqi": 80.0}, {"asymmetry_score": 0.08, "mqi": 0.0})
    a = out["metrics"]["asymmetry_score"]
    assert a["change_pct"] == pytest.approx(100.0) and a["direction"] == "higher"
    assert out["metrics"]["mqi"]["change_pct"] is None, "no % change from a zero baseline"
    text = json.dumps(out).lower()
    for word in ("deteriorat", "recover", "improv", "worse", "better"):
        assert word not in text


# ------------------------------------------------------------------ #
# model bundles
# ------------------------------------------------------------------ #

def _fake_bundle(tmp_path, **overrides):
    import joblib
    import sklearn
    from sklearn.dummy import DummyClassifier

    n_feat = len(F.bilateral_feature_names())
    model = DummyClassifier(strategy="prior")
    model.fit(np.zeros((4, n_feat)), ["walking", "walking", "walking", "sitting"])
    d = tmp_path / "activity_bilateral" / "v1"
    d.mkdir(parents=True)
    joblib.dump(model, d / "model.joblib")
    meta = {
        "name": "activity_bilateral", "version": "v1", "task": "activity",
        "model_type": "test", "model_file": "model.joblib",
        "model_sha256": sha256_file(d / "model.joblib"),
        "feature_version": F.FEATURE_VERSION, "preprocessing_version": PREPROCESSING_VERSION,
        "sklearn_version": sklearn.__version__,
        "input": {"kind": "bilateral", "rate_hz": 25.0, "window_s": 2.0},
        "classes": ["sitting", "walking"], "confidence_threshold": 0.8,
        "dataset": {"name": "test", "placements": ["SHANK"]},
        "validation_status": {"rehabsense_hardware": "NOT_VALIDATED"},
    }
    meta.update(overrides)
    (d / "bundle.json").write_text(json.dumps(meta))
    return d


def test_bundle_loads_and_low_probability_is_reported_low_confidence(tmp_path):
    bundle = ModelBundle.load(_fake_bundle(tmp_path))
    ts = np.arange(0, 2.5, 0.01)
    data = np.zeros((len(ts), 12))
    data[:, 2] = data[:, 8] = 1.0
    g0 = {"LEFT": np.array([0, 0, 1.0]), "RIGHT": np.array([0, 0, 1.0])}
    uncal = classify_window(bundle, ts, data, {"LEFT": True, "RIGHT": True}, {"LEFT": "SHANK"})
    assert uncal["status"] == "INSUFFICIENT_DATA" and "Calibration required" in uncal["message"]
    out = classify_window(bundle, ts, data, {"LEFT": True, "RIGHT": True}, {"LEFT": "SHANK"}, g0)
    # Prior is 0.75 < threshold 0.8: the candidate is kept, the answer is not.
    assert out["status"] == "LOW_CONFIDENCE"
    assert out["activity"] is None and out["candidate"] == "walking"
    assert out["domain"]["hardware_validated"] is False
    single = classify_window(bundle, ts, data, {"LEFT": True, "RIGHT": False}, {}, g0)
    assert single["status"] == "INSUFFICIENT_DATA"


def test_bundle_refuses_feature_version_mismatch(tmp_path):
    with pytest.raises(BundleError):
        ModelBundle.load(_fake_bundle(tmp_path, feature_version="other"))


def test_bundle_refuses_tampered_model_file(tmp_path):
    d = _fake_bundle(tmp_path)
    with open(d / "model.joblib", "ab") as fh:
        fh.write(b"tampered")
    with pytest.raises(BundleError):
        ModelBundle.load(d)


def test_no_model_reports_unavailable():
    out = classify_window(None, np.arange(10) / 100, np.zeros((10, 12)), {}, {})
    assert out["status"] == "MODEL_UNAVAILABLE" and out["confidence"] is None


def test_processor_treats_a_frozen_imu_as_missing():
    """A hung I2C bus repeats one reading; that must not look like a still leg."""
    from app.sensing.processor import DualSessionProcessor

    h = hello(force=0)
    model = DualImuModel(exercise="SQUAT", seed=6)
    proc = DualSessionProcessor(1, "SQUAT", h)
    proc.on_connect(h)
    frozen = None
    late = []
    for k in range(0, 3500, 10):
        batch = []
        for i in range(k, k + 10):
            s = model.sample(i / 100)
            if i >= 2000:
                frozen = frozen or s["imu_left"]
                s["imu_left"] = frozen
            batch.append(DualSample(ts=i / 100, seq=i, **s))
        events = proc.process(batch, arrival=1000 + k / 100)
        if k >= 2500:   # windows that start after the freeze was detected
            late += [e.payload for e in events if e.type == "hw_ml_update"]
    assert len(late) >= 10
    assert proc.monitor.frozen_flags["LEFT"]
    assert proc.connection_event().payload["imus"]["LEFT"]["state"] == "FROZEN"
    assert all(u["bilateral"]["status"] == "SINGLE_SIDE" for u in late)


def test_effective_rate_counts_losses_unlike_median_interval():
    m = StreamMonitor(declared_rate_hz=100)
    seq = 0
    for k in range(100):              # 10 s at 100 Hz, every 10th packet lost
        ts = np.arange(seq, seq + 10) / 100.0
        if k % 10 != 3:
            m.observe(ts, np.arange(seq, seq + 10), np.ones((10, 13)), arrival=float(ts[-1]))
        seq += 10
    d = m.as_dict()
    assert d["measured_rate_hz"] == pytest.approx(100.0, abs=0.01)
    assert d["effective_rate_hz"] == pytest.approx(90.0, abs=1.0)
    assert d["loss_ratio"] == pytest.approx(0.1, abs=0.01)
    assert d["force_available_ratio"] == [1.0]


def test_processor_reports_explicit_unavailable_codes():
    from app.sensing.processor import DualSessionProcessor

    h = hello(force=1, right=True)
    model = DualImuModel(exercise="SQUAT", seed=2, right=SideConfig(present=False))
    proc = DualSessionProcessor(1, "SQUAT", h)
    proc.on_connect(h)
    for k in range(0, 1200, 10):
        proc.process([DualSample(ts=i / 100, seq=i, **model.sample(i / 100)) for i in range(k, k + 10)],
                     arrival=1000 + k / 100)
    alerts = proc.connection_event().payload["alerts"]
    right = [a for a in alerts if a["code"] == "RIGHT_IMU_UNAVAILABLE"]
    assert len(right) == 1 and right[0]["reason"] == "NO_READINGS"
    assert not any(a["code"] == "LEFT_IMU_UNAVAILABLE" for a in alerts)
    proc.on_disconnect()
    assert {a["reason"] for a in proc.sensor_alerts() if "IMU" in a["code"]} == {"DEVICE_DISCONNECTED"}
