"""Training-path vs hardware-path parity for a deployed bundle.

    ml/.venv/bin/python ml/scripts/parity_check.py [bundle_dir]

Question answered: if the device delivered the *same movement* the model was
trained on, would the server compute the same inputs and the same answer?

  training path  : Daily & Sports window at 25 Hz -> features (as in training)
  hardware path  : the same segment re-expressed as a device stream --
                   upsampled to 100 Hz, MPU6050 quantisation (+-4 g /
                   +-500 dps LSB), 1 ms timestamp jitter, NaN-free --
                   -> app.sensing.inference.classify_window (the exact
                   server code: prepare_model_input, features, model)

Reports per-feature relative difference and prediction agreement. This checks
*preprocessing consistency*, not accuracy, and it is not hardware validation:
the "device stream" is derived from public data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rehabsense_ml  # noqa: E402,F401
import numpy as np  # noqa: E402

from app.sensing import features as F  # noqa: E402
from app.sensing.inference import ModelBundle, classify_window, find_bundle  # noqa: E402
from app.sensing.windowing import prepare_model_input  # noqa: E402
from rehabsense_ml import ARTIFACT_DIR, REPORT_DIR  # noqa: E402
from rehabsense_ml.datasets import daily_sports  # noqa: E402

ACC_LSB, GYRO_LSB = 1 / 8192, 1 / 65.5


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else find_bundle(ARTIFACT_DIR, "activity_bilateral")
    bundle = ModelBundle.load(path)
    rate, w = bundle.rate_hz, bundle.window_s
    n = int(round(w * rate))
    rng = np.random.default_rng(0)
    recs = daily_sports.load()
    idx = rng.choice(len(recs), size=min(800, len(recs)), replace=False)
    agree, rel_err, statuses = [], [], {}
    for i in idx:
        r = recs[i]
        # training path: last full window of the segment at native 25 Hz
        L, R = r.left[-n:], r.right[-n:]
        x_train = F.bilateral_features(L[None], R[None], rate, r.neutral_left, r.neutral_right)
        p_train = bundle.model.predict(x_train)[0]
        # hardware path: device-like 100 Hz stream of the whole segment
        t25 = np.arange(len(r.left)) / 25.0
        t100 = np.arange(0, t25[-1] + 1e-9, 0.01)
        dev = np.column_stack([np.interp(t100, t25, c) for c in np.column_stack([r.left, r.right]).T])
        dev[:, [0, 1, 2, 6, 7, 8]] = np.round(dev[:, [0, 1, 2, 6, 7, 8]] / ACC_LSB) * ACC_LSB
        dev[:, [3, 4, 5, 9, 10, 11]] = np.round(dev[:, [3, 4, 5, 9, 10, 11]] / GYRO_LSB) * GYRO_LSB
        ts = t100 + rng.normal(0, 0.001, len(t100))
        ts = np.maximum.accumulate(ts)
        ts[-1] = t25[-1]          # window ends at the same instant as the training window
        out = classify_window(bundle, ts, dev, {"LEFT": True, "RIGHT": True},
                              {"LEFT": "SHANK", "RIGHT": "SHANK"},
                              {"LEFT": r.neutral_left, "RIGHT": r.neutral_right})
        statuses[out["status"]] = statuses.get(out["status"], 0) + 1
        hw_pred = out.get("candidate")
        agree.append(hw_pred == p_train)
        grid = prepare_model_input(ts, dev, rate, t_start=ts[-1] - w + 1 / rate, n=n)
        x_hw = F.bilateral_features(grid[None, :, 0:6], grid[None, :, 6:12], rate,
                                    r.neutral_left, r.neutral_right)
        scale = np.maximum(np.abs(x_train), 1e-3)
        rel_err.append(np.median(np.abs(x_hw - x_train) / scale))
    report = {
        "bundle": f"{bundle.name}/{bundle.version}",
        "windows": len(idx),
        "prediction_agreement": round(float(np.mean(agree)), 4),
        "median_relative_feature_difference": round(float(np.median(rel_err)), 4),
        "p95_relative_feature_difference": round(float(np.percentile(rel_err, 95)), 4),
        "hardware_path_status_counts": statuses,
        "what_differs": "upsampling 25->100 Hz, MPU6050 quantisation, 1 ms jitter, then the "
                        "server's anti-alias + resample back to 25 Hz",
        "scope": "Preprocessing consistency on public data replayed in device format. "
                 "NOT hardware validation.",
    }
    (REPORT_DIR / "parity_check.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
