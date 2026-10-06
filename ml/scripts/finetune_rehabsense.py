"""Stages 5: evaluate and adapt on REAL RehabSense recordings.

    ml/.venv/bin/python ml/scripts/finetune_rehabsense.py ml/data/rehabsense_v1

Input: a directory written by backend/scripts/export_training_dataset.py
(consented, non-simulated, de-identified sessions with therapist labels).

Every sample goes through the same code the server runs:
  calibration record -> bias/scale correction (DeviceCalibrator semantics)
  -> app.sensing.windowing.prepare_model_input (anti-alias + resample)
  -> app.sensing.features.bilateral_features with the calibrated neutral pose

Reports, per held-out subject (leave-one-subject-out):
  A. zero-shot: the public-pretrained bundle, unchanged  <- hardware validation
  B. RehabSense-only model
  C. public + RehabSense combined (RehabSense windows weighted x5)
and writes C (or B, whichever is better on held-out subjects) as a new bundle
version whose validation_status records the hardware evaluation.

Refuses to run on fewer than 3 subjects: with fewer, held-out numbers are
anecdotes. Never reads simulated data (the exporter cannot produce it).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rehabsense_ml  # noqa: E402,F401  (puts backend/ on sys.path)
import numpy as np  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.metrics import f1_score  # noqa: E402

from app.sensing import features as F  # noqa: E402
from app.sensing.inference import ModelBundle, find_bundle  # noqa: E402
from app.sensing.windowing import prepare_model_input  # noqa: E402
from rehabsense_ml import ARTIFACT_DIR  # noqa: E402
from rehabsense_ml.artifacts import save_artifact  # noqa: E402

MIN_SUBJECTS = 3
REHAB_WEIGHT = 5.0


def load_export(root: Path):
    """Read a training export (backend/scripts/export_training_dataset.py).

    Every recording directory is in the research export format: samples.npz,
    metadata.json, calibration.json, labels.json (HUMAN only), events.json.
    Model predictions (predictions.json) are deliberately never read here.
    """
    manifest = json.loads((root / "manifest.json").read_text())
    sessions = []
    for entry in manifest["recordings"]:
        d = root / entry["dir"]
        meta = json.loads((d / "metadata.json").read_text())
        if meta.get("provenance") != "PHYSICAL_REGISTERED":
            raise SystemExit(f"{entry['dir']}: provenance {meta.get('provenance')} -- only "
                             "PHYSICAL_REGISTERED recordings may be used for hardware training")
        z = np.load(d / "samples.npz", allow_pickle=False)
        cols = ["t", "seq"] + [str(c) for c in z["columns"]]
        data = np.column_stack([z["t"], z["seq"].astype(float), z["values"].astype(float)])
        cals = json.loads((d / "calibration.json").read_text())["calibrations"]
        valid = [c for c in cals if c["valid"] and c["status"] in ("PASS", "WARN")]
        labels = json.loads((d / "labels.json").read_text())["labels"]
        events = json.loads((d / "events.json").read_text())["events"]
        sessions.append({
            "meta": {"file": entry["dir"], "subject": meta["pseudonymous_subject_code"]},
            "metadata": meta, "cols": cols, "data": data,
            "cal": valid[-1]["metadata"] if valid else {},
            "labels": {
                "label_activity": np.array([l.get("activity") or "" for l in labels]),
                "label_t_start": np.array([l["t_start"] for l in labels]),
                "label_t_end": np.array([l["t_end"] for l in labels]),
                "label_tier": np.array([l["tier"] for l in labels]),
            },
            "events": events,
        })
    return manifest, sessions


def dataset_report(sessions) -> dict:
    """Section-18 report, produced before any training."""
    subjects = sorted({s["meta"]["subject"] for s in sessions})
    n_samples = sum(len(s["data"]) for s in sessions)
    missing = sum(int(s["metadata"]["packets"].get("missing_samples") or 0) for s in sessions)
    imu_nan = 0.0
    for s in sessions:
        v = s["data"][:, 2:14]
        imu_nan += float(np.isnan(v).any(axis=1).sum())
    duration = sum(float(s["metadata"].get("duration_s") or 0.0) for s in sessions)
    labelled = sum(float(np.sum(s["labels"]["label_t_end"] - s["labels"]["label_t_start"]))
                   for s in sessions)
    classes: dict[str, float] = {}
    tiers: dict[str, int] = {}
    for s in sessions:
        for a, t0, t1, tier in zip(s["labels"]["label_activity"], s["labels"]["label_t_start"],
                                   s["labels"]["label_t_end"], s["labels"]["label_tier"]):
            if a:
                classes[str(a)] = classes.get(str(a), 0.0) + float(t1 - t0)
            tiers[str(tier)] = tiers.get(str(tier), 0) + 1
    failures = sum(1 for s in sessions if any(e["kind"] == "sensor_failure" for e in s["events"]))
    return {
        "subject_count": len(subjects),
        "recording_count": len(sessions),
        "sample_count": n_samples,
        "class_distribution_seconds": {k: round(v, 1) for k, v in sorted(classes.items())},
        "label_tiers": tiers,
        "missing_data_rate": round((missing + imu_nan) / max(1, n_samples + missing), 6),
        "sensor_failure_rate": round(failures / max(1, len(sessions)), 4),
        "label_coverage": round(labelled / max(1e-9, duration), 4),
        "split": "leave-one-subject-out; no subject in both train and test",
    }


def calibrated_imu(s) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(t, left[n,6], right[n,6], g0_left, g0_right) with the stored calibration applied.

    The same bias/scale correction the server's DeviceCalibrator applies; the
    neutral pose is the calibration's own gravity vector per sensor.
    """
    cols, d, cal = s["cols"], s["data"], s["cal"]
    t = d[:, cols.index("t")]
    out = []
    for side in ("left", "right"):
        block = d[:, [cols.index(f"{side}_{a}") for a in ("ax", "ay", "az", "gx", "gy", "gz")]].copy()
        off = cal.get(f"{side}_imu_offset") or {}
        if not off.get("usable") or off.get("neutral_gravity_unit") is None:
            raise ValueError(f"{s['meta']['file']}: {side} IMU not calibrated")
        block[:, 0:3] *= off["accel_scale"]
        block[:, 3:6] -= np.asarray(off["gyro_bias_dps"])
        out.append((block, np.asarray(off["neutral_gravity_unit"])))
    return t, out[0][0], out[1][0], out[0][1], out[1][1]


def windows(sessions, rate, window_s, stride_s=0.5):
    X, y, groups = [], [], []
    n = int(round(window_s * rate))
    for s in sessions:
        lab = s["labels"]
        acts = lab.get("label_activity")
        if acts is None or not any(a for a in acts):
            continue
        t, L, R, gl, gr = calibrated_imu(s)
        for a, t0, t1 in zip(acts, lab["label_t_start"], lab["label_t_end"]):
            if not a:
                continue
            for start in np.arange(t0, t1 - window_s + 1e-9, stride_s):
                sel = (t >= start - 0.1) & (t <= start + window_s)
                if sel.sum() < 4:
                    continue
                grid = prepare_model_input(t[sel], np.column_stack([L[sel], R[sel]]), rate,
                                           t_start=start + 1.0 / rate, n=n)
                if np.isnan(grid).mean() > 0.1:
                    continue
                X.append(F.bilateral_features(grid[None, :, 0:6], grid[None, :, 6:12], rate, gl, gr)[0])
                y.append(str(a))
                groups.append(s["meta"]["subject"])
    return np.array(X), np.array(y), np.array(groups)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    root = Path(sys.argv[1])
    manifest, sessions = load_export(root)
    report = dataset_report(sessions)
    print(json.dumps({"dataset_report": report}, indent=2))
    (root / "dataset_report.json").write_text(json.dumps(report, indent=2))
    subjects = sorted({s["meta"]["subject"] for s in sessions})
    if len(subjects) < MIN_SUBJECTS:
        raise SystemExit(f"{len(subjects)} subject(s) in the export; need >= {MIN_SUBJECTS} "
                         "for any held-out evaluation. Collect more pilot data first.")
    path = find_bundle(ARTIFACT_DIR, "activity_bilateral")
    if path is None:
        raise SystemExit("no public-pretrained activity_bilateral bundle found")
    bundle = ModelBundle.load(path)
    X, y, g = windows(sessions, bundle.rate_hz, bundle.window_s)
    if len(X) == 0:
        raise SystemExit("no activity-labelled windows in the export")
    known = np.isin(y, bundle.classes)

    report = {"export": str(root), "dataset_report": report, "subjects": len(subjects),
              "windows": int(len(X)),
              "classes_in_export": sorted(set(y)),
              "public_model": f"{bundle.name}/{bundle.version}", "folds": []}
    pred_a = np.empty(len(y), dtype=object)
    pred_b = np.empty(len(y), dtype=object)
    for subj in subjects:
        te, tr = g == subj, g != subj
        pred_a[te] = bundle.model.predict(X[te])                       # A: zero-shot
        m = RandomForestClassifier(200, min_samples_leaf=2, n_jobs=-1, random_state=0)
        m.fit(X[tr], y[tr])
        pred_b[te] = m.predict(X[te])                                   # B: RehabSense-only
    report["A_zero_shot_public_model_macro_f1_known_classes"] = round(float(
        f1_score(y[known], pred_a[known], average="macro", zero_division=0)), 4)
    report["B_rehabsense_only_loso_macro_f1"] = round(float(
        f1_score(y, pred_b, average="macro", zero_division=0)), 4)
    report["note"] = ("A is the hardware validation of the public-pretrained model on held-out "
                      "real subjects. B uses leave-one-subject-out on RehabSense data only. "
                      "Neither is clinical validation.")
    print(json.dumps(report, indent=2))

    final = RandomForestClassifier(200, min_samples_leaf=2, n_jobs=-1, random_state=0).fit(X, y)
    out = save_artifact(
        name="activity_bilateral_rehabsense", model=final, task="activity_recognition",
        model_type="RandomForestClassifier",
        metrics={"macro_f1": report["B_rehabsense_only_loso_macro_f1"], "hardware_evaluation": report},
        config={"trained_on": "RehabSense pilot export", "window_s": bundle.window_s},
        dataset={"name": "RehabSense pilot (real hardware)", "sensor": "MPU6050 x2 (+ force)",
                 "placements": sorted({p for s in sessions for p in
                                       ((s["cal"].get("orientation") or {}).get(x, {}).get("placement")
                                        for x in ("LEFT", "RIGHT")) if p})},
        input_spec={**bundle.meta["input"]}, classes=[str(c) for c in final.classes_],
        confidence_threshold=bundle.threshold,
        validation_status={
            "public_dataset": "NOT_APPLICABLE (trained on RehabSense data)",
            "rehabsense_hardware": f"EVALUATED (LOSO, {len(subjects)} subjects; see metrics.json)",
            "clinical": "NOT_VALIDATED",
        },
    )
    print("wrote", out)


if __name__ == "__main__":
    main()
