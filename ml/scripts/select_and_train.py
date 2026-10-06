"""Select models from a benchmark report by a stated rule, then train bundles.

    ml/.venv/bin/python ml/scripts/select_and_train.py ml/reports/benchmark_<stamp>.json

Selection rule (fixed before looking at results, applied mechanically):

  1. Deployable candidates are feature models on orientation-invariant
     features (the backend runs scikit-learn bundles; see inference.py).
  2. Window length: the *shortest* window whose macro-F1 is within 0.01 of
     the best window for that model family. Shorter windows respond faster,
     and a difference under 0.01 is within fold-to-fold noise here.
  3. Among candidates at that window: highest macro-F1, subject to
       - rotation robustness drop <= 0.03 macro-F1 (strap orientation changes)
       - single-window p95 latency <= 50 ms
     ties within 0.01 broken by smaller model size.
  4. Deep models are reported alongside. If one beats the selected feature
     model by >= 0.02 macro-F1 *and* passes (3), the report recommends adding
     a deep-model runtime to the backend; it is not deployed silently.

Confidence threshold: from out-of-fold (subject-independent) probabilities of
the selected configuration, the lowest threshold at which the accuracy of
accepted windows reaches 0.90. Coverage at that threshold is recorded; below
it, the backend reports LOW_CONFIDENCE instead of an activity.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier  # noqa: E402

from rehabsense_ml import REPORT_DIR  # noqa: E402
from rehabsense_ml.artifacts import save_artifact  # noqa: E402
from rehabsense_ml.datasets import daily_sports, pamap2  # noqa: E402
from rehabsense_ml.evaluate import _augmented_features, feature_matrix, folds  # noqa: E402
from rehabsense_ml.windows import make_windows, single_side_from_bilateral  # noqa: E402

TARGET_ACCEPTED_ACCURACY = 0.90
MAX_ROTATION_DROP = 0.03
MAX_P95_MS = 50.0
WINDOW_TOLERANCE = 0.01
DEEP_MARGIN = 0.02

def _rf():
    return RandomForestClassifier(n_estimators=200, min_samples_leaf=2, n_jobs=-1,
                                  class_weight="balanced_subsample", random_state=0)


MAKERS = {
    "rf_invariant": _rf,
    "rf_invariant_aug": _rf,
    "hgb_invariant": lambda: HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.08, class_weight="balanced", random_state=0),
}


def choose(exps: dict, prefix: str) -> tuple[str, float, dict, list[str]]:
    notes = []
    rows = {k: v for k, v in exps.items() if k.startswith(prefix) and "_invariant" in k}
    by_model: dict[str, dict[float, dict]] = {}
    for k, v in rows.items():
        _, _, model, w = k.split("/")
        by_model.setdefault(model, {})[float(w[1:])] = v
    candidates = []
    for model, wins in by_model.items():
        best = max(r["macro_f1"] for r in wins.values())
        window = min(w for w, r in wins.items() if r["macro_f1"] >= best - WINDOW_TOLERANCE)
        r = wins[window]
        drop = r["macro_f1"] - r["robustness_macro_f1"]["rotation"]
        ok = drop <= MAX_ROTATION_DROP and r["latency_ms_p95"] <= MAX_P95_MS
        notes.append(f"{model}: window {window}s (best {best:.4f}), macroF1 {r['macro_f1']:.4f}, "
                     f"rotation drop {drop:.4f}, p95 {r['latency_ms_p95']} ms -> "
                     f"{'eligible' if ok else 'rejected'}")
        if ok:
            candidates.append((r["macro_f1"], -r["model_bytes"], model, window, r))
    if not candidates:
        raise SystemExit("no candidate passed the robustness/latency rule:\n" + "\n".join(notes))
    candidates.sort(reverse=True)
    top = candidates[0]
    close = [c for c in candidates if top[0] - c[0] <= 0.01]
    pick = max(close, key=lambda c: c[1])   # smallest model among near-ties
    notes.append(f"selected {pick[2]} at {pick[3]}s")
    return pick[2], pick[3], pick[4], notes


def fit(model_name: str, ws, X, idx, rng):
    """Fit exactly as benchmarked: `_aug` variants add a device-like copy."""
    m = MAKERS[model_name]()
    if model_name.endswith("_aug"):
        Xa = _augmented_features(ws.subset(idx), "invariant", rng)
        m.fit(np.concatenate([X[idx], Xa]), np.concatenate([ws.y[idx], ws.y[idx]]))
    else:
        m.fit(X[idx], ws.y[idx])
    return m


def oof_threshold(ws, model_name: str) -> tuple[float, float, dict]:
    X = feature_matrix(ws, "invariant")
    proba = np.zeros(len(ws))
    correct = np.zeros(len(ws), dtype=bool)
    rng = np.random.default_rng(0)
    for tr, te in folds(ws, 4):
        m = fit(model_name, ws, X, tr, rng)
        p = m.predict_proba(X[te])
        proba[te] = p.max(1)
        correct[te] = m.classes_[p.argmax(1)] == ws.y[te]
    curve = {}
    chosen = None
    for t in np.round(np.arange(0.30, 0.96, 0.05), 2):
        acc = proba >= t
        if acc.sum() == 0:
            continue
        a = float(correct[acc].mean())
        cov = float(acc.mean())
        curve[str(t)] = {"accepted_accuracy": round(a, 4), "coverage": round(cov, 4)}
        if chosen is None and a >= TARGET_ACCEPTED_ACCURACY:
            chosen = (float(t), cov)
    if chosen is None:
        chosen = (0.95, curve.get("0.95", {}).get("coverage", 0.0))
    return chosen[0], chosen[1], curve


def train(kind: str, ws, model_name: str, window: float, bench: dict, notes: list[str],
          dataset: dict, placements: list[str]) -> Path:
    threshold, coverage, curve = oof_threshold(ws, model_name)
    X = feature_matrix(ws, "invariant")
    model = fit(model_name, ws, X, np.arange(len(ws)), np.random.default_rng(1))
    classes = [str(c) for c in model.classes_]
    metrics = {**bench, "confidence_threshold": threshold, "coverage_at_threshold": round(coverage, 4),
               "threshold_curve": curve,
               "evaluation": "GroupKFold(4) by subject; out-of-fold; see benchmark report"}
    name = "activity_bilateral" if kind == "bilateral" else "activity_single_side"
    return save_artifact(
        name=name, model=model, task="activity_recognition",
        model_type=type(model).__name__, metrics=metrics,
        config={"model": model_name, "params": model.get_params(), "window_s": window,
                "stride_s": 0.5, "selection_notes": notes,
                "selection_rule": __doc__.split("Confidence threshold")[0].strip()},
        dataset={**dataset, "placements": placements},
        input_spec={"kind": kind, "rate_hz": ws.rate_hz, "window_s": window,
                    "channels": "orientation-invariant (features.INVARIANT_CHANNELS)",
                    "force_inputs": 0},
        classes=classes, confidence_threshold=threshold,
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    report = json.loads(Path(sys.argv[1]).read_text())
    exps = report["experiments"]
    ds = daily_sports.load()
    pm = pamap2.load()

    # Bilateral: Daily & Sports only (the one dataset with a real sensor on each leg).
    model, window, bench, notes = choose(exps, "B1/bilateral/")
    deep = {k: v for k, v in exps.items() if k.startswith("B2/bilateral/") and "rf_raw" not in k}
    for k, v in deep.items():
        drop = v["macro_f1"] - v["robustness_macro_f1"]["rotation"]
        better = v["macro_f1"] - bench["macro_f1"]
        verdict = ("RECOMMEND adding a deep runtime"
                   if better >= DEEP_MARGIN and drop <= MAX_ROTATION_DROP
                   and v["latency_ms_p95"] <= MAX_P95_MS else "not adopted")
        notes.append(f"{k}: macroF1 {v['macro_f1']:.4f} ({better:+.4f} vs selected), "
                     f"rotation drop {drop:.4f} -> {verdict}")
    ws = make_windows(ds, window, 0.5, bilateral=True)
    bi = train("bilateral", ws, model, window, bench, notes,
               daily_sports.manifest(), daily_sports.PLACEMENTS)
    print("bilateral:", bi)
    for n in notes:
        print("  ", n)

    # Single IMU: Daily & Sports legs (each a real sensor) + PAMAP2 ankle.
    singles = {k.split("/")[2]: v for k, v in exps.items()
               if k.startswith("S1/single/") and "_invariant" in k}
    s_model = max(singles, key=lambda m: singles[m]["macro_f1"]) if singles else model
    s_bench = exps.get(f"S1/single/{s_model}/w2.0", {})
    single = make_windows(single_side_from_bilateral(ds) + pm, 2.0, 0.5, bilateral=False)
    manifest = {"name": "Daily & Sports (each leg) + PAMAP2 (ankle)",
                "sensor": "Xsens MTx and Colibri IMUs",
                "components": [daily_sports.manifest(), pamap2.manifest()]}
    sg = train("single_side", single, s_model, 2.0, s_bench,
               [f"single-side model: {s_model} at 2.0 s (S1 benchmark)"], manifest,
               daily_sports.PLACEMENTS + pamap2.PLACEMENTS)
    print("single side:", sg)
    (REPORT_DIR / "selection.json").write_text(json.dumps(
        {"report": sys.argv[1], "bilateral": str(bi), "single_side": str(sg), "notes": notes},
        indent=2))


if __name__ == "__main__":
    main()
