"""Guards on the ML pipeline's integrity rules (leakage, no fake bilateral data, shapes)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rehabsense_ml.datasets import Recording  # noqa: E402
from rehabsense_ml.evaluate import feature_matrix, folds  # noqa: E402
from rehabsense_ml.transforms import PERTURBATIONS  # noqa: E402
from rehabsense_ml.windows import make_windows, single_side_from_bilateral  # noqa: E402


def _rec(subject, label, n=125, bilateral=True, seed=0):
    rng = np.random.default_rng(seed)
    imu = rng.normal(size=(n, 6)) + np.array([0, 0, 1, 0, 0, 0])
    return Recording(subject, label, "x", 25.0, imu, imu.copy() if bilateral else None,
                     neutral_left=np.array([0, 0, 1.0]),
                     neutral_right=np.array([0, 0, 1.0]) if bilateral else None)


def test_bilateral_windows_refuse_single_imu_recordings():
    with pytest.raises(ValueError):
        make_windows([_rec("s1", "walking", bilateral=False)], 2.0, 0.5, bilateral=True)


def test_single_side_split_keeps_each_real_sensor_and_its_own_neutral():
    r = _rec("s1", "walking")
    r.neutral_right = np.array([1.0, 0, 0])
    out = single_side_from_bilateral([r])
    assert len(out) == 2 and all(o.right is None for o in out)
    assert np.allclose(out[1].neutral_left, [1, 0, 0])


def test_folds_are_subject_disjoint():
    recs = [_rec(f"s{i}", lab, seed=i * 10 + j) for i in range(8)
            for j, lab in enumerate(["walking", "sitting"])]
    ws = make_windows(recs, 2.0, 0.5, bilateral=True)
    for tr, te in folds(ws, 4):
        assert not set(ws.groups[tr]) & set(ws.groups[te])


def test_rotation_perturbation_rotates_the_neutral_pose_too():
    rng = np.random.default_rng(0)
    imu = np.tile([[0, 0, 1.0, 0, 0, 0]], (3, 10, 1))
    g0 = np.tile([0, 0, 1.0], (3, 1))
    rot, g = PERTURBATIONS["rotation"](imu, g0, rng)
    assert np.allclose(rot[:, 0, 0:3], g)


def test_invariant_features_unchanged_by_rotation():
    recs = [_rec("s1", "walking", seed=3)]
    ws = make_windows(recs, 2.0, 0.5, bilateral=True)
    rng = np.random.default_rng(1)
    l, gl = PERTURBATIONS["rotation"](ws.left, ws.g0_left, rng)
    r, gr = PERTURBATIONS["rotation"](ws.right, ws.g0_right, rng)
    assert np.allclose(feature_matrix(ws, "invariant"),
                       feature_matrix(ws, "invariant", l, r, gl, gr), atol=1e-6)


def test_fusion_net_accepts_configurable_force_channels():
    torch = pytest.importorskip("torch")
    from rehabsense_ml.models.deep import FusionNet

    for n_force in (0, 1, 3):
        net = FusionNet(5, temporal="cnn", bilateral=True, n_force=n_force)
        x = torch.zeros(2, 9, 50)
        f = torch.zeros(2, n_force, 50) if n_force else None
        assert net(x, x, f).shape == (2, 5)
    single = FusionNet(4, temporal="cnn_lstm", bilateral=False)
    assert single(torch.zeros(3, 9, 50)).shape == (3, 4)


def test_daily_sports_calibration_segment_is_excluded():
    from rehabsense_ml import CACHE_DIR
    from rehabsense_ml.datasets import daily_sports

    if not (CACHE_DIR / "daily_sports.npz").exists():
        pytest.skip("dataset not extracted")
    recs = daily_sports.load()
    assert not any(r.source_activity == "a02" and r.meta["segment"] == 1 for r in recs)
    assert all(r.neutral_left is not None and r.neutral_right is not None for r in recs)


def test_finetune_refuses_non_physical_and_too_few_subjects(tmp_path):
    """Code-path fixtures only (not data)."""
    import json
    import subprocess

    root = Path(__file__).resolve().parents[1]
    script = str(root / "scripts" / "finetune_rehabsense.py")

    def make(base, provenance, subjects):
        base.mkdir()
        recs = []
        for i, subj in enumerate(subjects):
            d = base / f"r{i}"
            d.mkdir()
            (d / "metadata.json").write_text(json.dumps({
                "provenance": provenance, "pseudonymous_subject_code": subj, "duration_s": 1.0,
                "packets": {"missing_samples": 0}}))
            np.savez(d / "samples.npz", t=np.zeros(3), seq=np.arange(3), values=np.zeros((3, 12)),
                     columns=np.array([f"{s}_{a}" for s in ("left", "right")
                                       for a in ("ax", "ay", "az", "gx", "gy", "gz")]))
            (d / "calibration.json").write_text(json.dumps({"calibrations": []}))
            (d / "labels.json").write_text(json.dumps({"labels": []}))
            (d / "events.json").write_text(json.dumps({"events": []}))
            recs.append({"dir": f"r{i}"})
        (base / "manifest.json").write_text(json.dumps({"recordings": recs}))

    make(tmp_path / "sim", "SIMULATED", ["a", "b", "c"])
    r = subprocess.run([sys.executable, script, str(tmp_path / "sim")], capture_output=True, text=True)
    assert r.returncode != 0 and "only PHYSICAL_REGISTERED" in (r.stderr + r.stdout)

    make(tmp_path / "two", "PHYSICAL_REGISTERED", ["a", "b"])
    r = subprocess.run([sys.executable, script, str(tmp_path / "two")], capture_output=True, text=True)
    assert r.returncode != 0 and "need >= 3" in (r.stderr + r.stdout)
    rep = json.loads((tmp_path / "two" / "dataset_report.json").read_text())
    assert rep["subject_count"] == 2 and rep["recording_count"] == 2 and rep["label_coverage"] == 0
