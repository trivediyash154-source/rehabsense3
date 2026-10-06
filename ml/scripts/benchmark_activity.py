"""Benchmark activity models on the public datasets (stages 2-3).

    ml/.venv/bin/python ml/scripts/benchmark_activity.py [--quick]

Writes ml/reports/benchmark_<timestamp>.json and .md. Nothing is selected by
assumption: the final model is chosen from these numbers (see
select_and_train.py), and the report keeps every number, including the ones
that make a model look bad.

Experiments
  B1  bilateral (Daily & Sports, both legs): window length sweep, feature models
  B2  bilateral, 2 s windows: raw-axis vs invariant features, 1D CNN, CNN-LSTM,
      CNN with PAMAP2-pretrained encoder
  S1  single IMU (Daily & Sports legs as separate sensors + PAMAP2 ankle)
  X1  cross-dataset transfer: train on one dataset's sensors, test on the other
      (shared classes only) -- a direct measure of sensor/placement domain gap
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier  # noqa: E402
from sklearn.metrics import f1_score  # noqa: E402

from rehabsense_ml import REPORT_DIR  # noqa: E402
from rehabsense_ml.datasets import daily_sports, pamap2  # noqa: E402
from rehabsense_ml.evaluate import (  # noqa: E402
    evaluate_deep,
    evaluate_feature_model,
    feature_matrix,
    pretrain_encoder,
)
from rehabsense_ml.windows import make_windows, single_side_from_bilateral  # noqa: E402

LOG: list[str] = []


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    LOG.append(line)
    print(line, flush=True)


def rf():
    return RandomForestClassifier(n_estimators=200, min_samples_leaf=2, n_jobs=-1,
                                  class_weight="balanced_subsample", random_state=0)


def hgb():
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08,
                                          class_weight="balanced", random_state=0)


def brief(r: dict) -> str:
    rob = ", ".join(f"{k} {v:.3f}" for k, v in r.get("robustness_macro_f1", {}).items())
    return (f"acc {r['accuracy']:.3f} macroF1 {r['macro_f1']:.3f} folds {r['fold_macro_f1']} "
            f"| p50 {r['latency_ms_p50']} ms | {r['model_bytes'] / 1e6:.2f} MB | robust: {rob}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="fewer epochs/configs (smoke run)")
    args = ap.parse_args()
    epochs = 4 if args.quick else 15
    results: dict = {"started": datetime.now(timezone.utc).isoformat(), "quick": args.quick,
                     "host": {"platform": platform.platform(), "python": platform.python_version()},
                     "protocol": "GroupKFold(4) by subject; pooled test predictions",
                     "experiments": {}}

    ds = daily_sports.load()
    pm = pamap2.load()
    results["datasets"] = {"daily_sports": daily_sports.manifest(), "pamap2": pamap2.manifest()}
    log(f"loaded Daily&Sports {len(ds)} segments, PAMAP2 {len(pm)} recordings")

    # ---- B1: window sweep, bilateral feature models -------------------- #
    windows = [2.0] if args.quick else [1.0, 2.0, 3.0]
    for w in windows:
        ws = make_windows(ds, w, 0.5, bilateral=True)
        for name, make, aug in (("rf_invariant", rf, False), ("hgb_invariant", hgb, False),
                                ("rf_invariant_aug", rf, True)):
            if args.quick and name != "rf_invariant":
                continue
            key = f"B1/bilateral/{name}/w{w}"
            log(f"{key}: {len(ws)} windows")
            r = evaluate_feature_model(ws, make, "invariant", augment=aug)
            r.update({"window_s": w, "stride_s": 0.5, "n_windows": len(ws),
                      "response_delay_s": round(w / 2 + 0.5, 2)})
            results["experiments"][key] = r
            log(f"  {brief(r)}")

    # ---- B2: model families at 2 s -------------------------------------- #
    ws2 = make_windows(ds, 2.0, 0.5, bilateral=True)
    key = "B2/bilateral/rf_raw_axis/w2.0"
    log(f"{key}")
    r = evaluate_feature_model(ws2, rf, "raw")
    results["experiments"][key] = r
    log(f"  {brief(r)}")

    for temporal in ("cnn", "cnn_lstm"):
        key = f"B2/bilateral/{temporal}/w2.0"
        log(f"{key}")
        r = evaluate_deep(ws2, temporal, epochs=epochs)
        results["experiments"][key] = r
        log(f"  {brief(r)} | params {r['parameters']}")

    # Encoder pretrained on PAMAP2 ankle (different subjects, sensor, placement).
    pm_ws = make_windows(pm, 2.0, 0.5, bilateral=False)
    log(f"pretraining CNN encoder on PAMAP2 ({len(pm_ws)} windows)")
    enc = pretrain_encoder(pm_ws, "cnn", epochs=max(3, epochs // 2))
    key = "B2/bilateral/cnn_pretrained_pamap2/w2.0"
    r = evaluate_deep(ws2, "cnn", epochs=epochs, init_encoder=enc)
    results["experiments"][key] = r
    log(f"  {key}: {brief(r)}")

    # ---- S1: single IMU ------------------------------------------------- #
    single = single_side_from_bilateral(ds) + pm
    ws_s = make_windows(single, 2.0, 0.5, bilateral=False)
    for name, make, aug in (("rf_invariant", rf, False), ("rf_invariant_aug", rf, True)):
        if args.quick and name != "rf_invariant":
            continue
        key = f"S1/single/{name}/w2.0"
        log(f"{key}: {len(ws_s)} windows")
        r = evaluate_feature_model(ws_s, make, "invariant", augment=aug)
        results["experiments"][key] = r
        log(f"  {brief(r)}")
    key = "S1/single/cnn/w2.0"
    r = evaluate_deep(ws_s, "cnn", epochs=max(4, epochs * 2 // 3))
    results["experiments"][key] = r
    log(f"  {key}: {brief(r)}")

    # ---- X1: cross-dataset transfer (domain gap) ------------------------ #
    ds_single = make_windows(single_side_from_bilateral(ds), 2.0, 0.5, bilateral=False)
    shared = sorted(set(ds_single.y) & set(pm_ws.y))
    for (src_name, src), (dst_name, dst) in (
        (("daily_sports_legs", ds_single), ("pamap2_ankle", pm_ws)),
        (("pamap2_ankle", pm_ws), ("daily_sports_legs", ds_single)),
    ):
        s_idx = np.isin(src.y, shared)
        d_idx = np.isin(dst.y, shared)
        model = rf()
        model.fit(feature_matrix(src.subset(np.flatnonzero(s_idx))), src.y[s_idx])
        pred = model.predict(feature_matrix(dst.subset(np.flatnonzero(d_idx))))
        f1 = float(f1_score(dst.y[d_idx], pred, average="macro", zero_division=0))
        acc = float(np.mean(pred == dst.y[d_idx]))
        key = f"X1/transfer/{src_name}->{dst_name}"
        results["experiments"][key] = {"macro_f1": round(f1, 4), "accuracy": round(acc, 4),
                                       "classes": [str(c) for c in shared]}
        log(f"{key}: acc {acc:.3f} macroF1 {f1:.3f} on {shared}")

    results["finished"] = datetime.now(timezone.utc).isoformat()
    results["log"] = LOG
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORT_DIR / f"benchmark_{stamp}{'_quick' if args.quick else ''}.json"
    out.write_text(json.dumps(results, indent=2))
    log(f"wrote {out}")


if __name__ == "__main__":
    main()
