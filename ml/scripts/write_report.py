"""Generate ml/reports/REPORT.md from the JSON results (never hand-edited).

    ml/.venv/bin/python ml/scripts/write_report.py ml/reports/benchmark_<stamp>.json

Four evidence levels are kept in separate sections and never merged:
public-dataset, simulator, real RehabSense hardware, clinical.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
ARTIFACTS = ROOT / "artifacts"

DATASET = {"B1": "Daily & Sports (both legs)", "B2": "Daily & Sports (both legs)",
           "S1": "D&S legs (each) + PAMAP2 ankle"}
INPUT = {
    "rf_invariant": "invariant + neutral-pose features",
    "rf_invariant_aug": "same, + device-like augmentation",
    "hgb_invariant": "invariant + neutral-pose features",
    "rf_raw_axis": "raw-axis features (control)",
    "cnn": "9 ch/IMU sequence", "cnn_lstm": "9 ch/IMU sequence",
    "cnn_pretrained_pamap2": "9 ch/IMU sequence",
}
MODEL = {
    "rf_invariant": "Random forest", "rf_invariant_aug": "Random forest",
    "hgb_invariant": "Hist. gradient boosting", "rf_raw_axis": "Random forest",
    "cnn": "1D CNN", "cnn_lstm": "CNN-LSTM", "cnn_pretrained_pamap2": "1D CNN, PAMAP2-pretrained",
}


def load(name):
    p = REPORTS / name
    return json.loads(p.read_text()) if p.exists() else None


def main() -> None:
    bench = json.loads(Path(sys.argv[1]).read_text())
    exps = bench["experiments"]
    sel = load("selection.json") or {}
    L = ["# RehabSense ML report", "",
         f"Generated from `{Path(sys.argv[1]).name}`. Protocol: {bench['protocol']}.", "",
         "> Four evidence levels, reported separately. A number from one level is never "
         "evidence for another.", ""]

    L += ["## 1. Public-dataset performance (subject-independent)", "",
          "| Dataset | Model | Input | Window | Macro-F1 | Robustness (rotation / noise×3 / gyro bias / gain / rate 5%) | Latency p50 / p95 | Size |",
          "|---|---|---|---|---|---|---|---|"]
    for k, v in exps.items():
        if k.startswith("X1"):
            continue
        stage, _, model, w = k.split("/")
        r = v["robustness_macro_f1"]
        rob = " / ".join(f"{r[x]:.3f}" for x in ("rotation", "noise_x3", "gyro_bias", "accel_gain", "rate_5pct"))
        L.append(f"| {DATASET[stage]} | {MODEL.get(model, model)} | {INPUT.get(model, model)} | {w[1:]} s "
                 f"| **{v['macro_f1']:.3f}** | {rob} | {v['latency_ms_p50']:.2f} / {v['latency_ms_p95']:.2f} ms "
                 f"| {v['model_bytes'] / 1e6:.2f} MB |")
    uci = [load("stage1_uci_har_rf_metrics.json"), load("stage1_uci_har_hgb_metrics.json")]
    for name, m in zip(("Random forest", "Hist. gradient boosting"), uci):
        if m:
            L.append(f"| UCI HAR (waist phone, official split) | {name} | 561 UCI features (not deployable) "
                     f"| 2.56 s | **{m['macro_f1']:.3f}** | n/a | n/a | n/a |")
    L += ["", "**Cross-dataset transfer (sensor/placement domain gap):**", ""]
    for k, v in exps.items():
        if k.startswith("X1"):
            L.append(f"- {k.split('/', 2)[2]}: macro-F1 **{v['macro_f1']:.3f}**")
    L += ["", "A model trained on one dataset's leg sensors collapses on another dataset's ankle "
          "sensor. That is the size of the domain gap the RehabSense hardware must be expected to "
          "have until the model is evaluated and adapted on device data.", ""]

    if sel:
        L += ["### Selected model (rule fixed before results; see select_and_train.py)", ""]
        L += [f"- {n}" for n in sel.get("notes", [])]
        for kind in ("bilateral", "single_side"):
            b = json.loads((Path(sel[kind]) / "bundle.json").read_text())
            m = json.loads((Path(sel[kind]) / "metrics.json").read_text())
            c = json.loads((Path(sel[kind]) / "config.json").read_text())
            L += ["", f"**{b['name']}/{b['version']}**", "",
                  f"- input: {b['input']['kind']}, per IMU ax ay az [g] gx gy gz [deg/s] + calibrated "
                  f"neutral gravity vector; force inputs: {b['input']['force_inputs']}",
                  f"- sampling: device stream → `prepare_model_input` (moving-average anti-alias, linear "
                  f"resample) → {b['input']['rate_hz']} Hz",
                  f"- window {b['input']['window_s']} s, stride {c.get('stride_s')} s (server: HW_STRIDE_S)",
                  f"- features: `{b['feature_version']}` ({'308' if kind == 'bilateral' else '153'}+ values: "
                  "6 orientation-invariant channels × 24 statistics, jerk, 8 neutral-pose posture features"
                  f"{', 18 left/right cross features' if kind == 'bilateral' else ''})",
                  f"- preprocessing `{b['preprocessing_version']}`, model {b['model_type']} "
                  f"(200 trees, min_samples_leaf 2, balanced class weights), sklearn {b['sklearn_version']}",
                  f"- classes: {', '.join(b['classes'])}",
                  f"- confidence threshold {b['confidence_threshold']} (coverage "
                  f"{m.get('coverage_at_threshold')}). Derived from public-data out-of-fold "
                  "probabilities; **must be re-derived on RehabSense data** — probabilities are not "
                  "calibrated for the device domain.",
                  f"- model SHA-256 `{b['model_sha256'][:16]}…`, validation status: {b['validation_status']}"]

    sim = load("simulator_evaluation.json")
    L += ["", "## 2. Simulator performance (synthetic data, known ground truth)", "",
          "Pipeline-mechanics evidence only. The simulator's kinematics are idealised; its activity "
          "predictions are **not meaningful** (simulated walking is classified as other_exercise "
          "because its signal is not real gait).", ""]
    if sim:
        L += ["| Exercise | ROM-proxy error L / R | Reps detected L / R (≈ simulated) |", "|---|---|---|"]
        for ex, v in sim["rom_proxy"].items():
            reps = sim["repetitions"][ex]
            L.append(f"| {ex} | {v.get('LEFT', {}).get('error_pct')}% / {v.get('RIGHT', {}).get('error_pct')}% "
                     f"| {reps['detected'].get('LEFT')} / {reps['detected'].get('RIGHT')} "
                     f"(≈{reps['simulated_cycles_per_side_approx']}) |")
        L += ["", "Asymmetry vs injected left-side severity:", ""]
        for ex, row in sim["asymmetry_vs_severity"].items():
            L.append(f"- {ex}: " + ", ".join(f"sev {k} → {v}" for k, v in row.items()
                                              if k != "monotonic_increase")
                     + f" (monotonic: {row['monotonic_increase']})")
        L += ["", "Injected faults detected by hardware-data validation: " +
              ", ".join(f"{k}: {'yes' if v['detected'] else 'NO'}" for k, v in sim["fault_detection"].items())]
    par = load("parity_check.json")
    rep = load("device_pipeline_replay.json")
    L += ["", "### Training-path ↔ device-path consistency (public data in device format)", ""]
    if par:
        L.append(f"- Parity (same window, device format at 100 Hz, quantised, jittered): prediction "
                 f"agreement **{par['prediction_agreement']:.3f}**, median feature difference "
                 f"{par['median_relative_feature_difference']:.3f}")
    if rep:
        L.append(f"- Full DualSessionProcessor replay (calibration → windows → model): agreement with "
                 f"label **{rep['agreement_with_label']:.3f}** over {rep['windows_scored']} windows "
                 "(subjects seen in training — integrity check, not generalisation)")

    L += ["", "## 3. Real RehabSense hardware performance", "",
          "**NOT VALIDATED.** No recordings from the ESP32 + 2× MPU6050 + FSR device exist yet. "
          "The collection protocol (`/api/ml/pilot-status`, docs/PILOT_DATA_COLLECTION.md) and the "
          "evaluation script (`finetune_rehabsense.py`, zero-shot then adapted, leave-one-subject-out) "
          "are ready; this section stays empty until they produce numbers.", "",
          "## 4. Clinical validation", "", "**NOT VALIDATED.** Nothing here is a clinical claim."]
    (REPORTS / "REPORT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
