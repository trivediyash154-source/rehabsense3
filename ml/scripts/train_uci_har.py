"""Stage 1: UCI HAR baseline on the provided Kaggle CSV (561 precomputed features).

    ml/.venv/bin/python ml/scripts/train_uci_har.py

A public benchmark only. The archive has no raw signals, so these features
cannot be reproduced from RehabSense data and this model is never deployed
(its artifact is marked `deployable: false`). It exists to check the training
and evaluation tooling against a well-known reference point.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier  # noqa: E402
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score  # noqa: E402

from rehabsense_ml.artifacts import save_artifact  # noqa: E402
from rehabsense_ml.datasets import uci_har  # noqa: E402


def main() -> None:
    (Xtr, ytr, gtr), (Xte, yte, gte), feats = uci_har.load()
    assert not (set(gtr) & set(gte)), "official UCI HAR split must be subject-disjoint"
    classes = sorted(set(ytr))
    for name, model in (
        ("rf", RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=0)),
        ("hgb", HistGradientBoostingClassifier(max_iter=300, random_state=0)),
    ):
        t0 = time.perf_counter()
        model.fit(Xtr, ytr)
        secs = time.perf_counter() - t0
        pred = model.predict(Xte)
        metrics = {
            "accuracy": round(float(accuracy_score(yte, pred)), 4),
            "macro_f1": round(float(f1_score(yte, pred, average="macro")), 4),
            "per_class_f1": dict(zip(classes, [round(float(v), 4) for v in
                                               f1_score(yte, pred, average=None, labels=classes)])),
            "confusion_matrix": confusion_matrix(yte, pred, labels=classes).tolist(),
            "classes": classes,
            "train_seconds": round(secs, 1),
            "split": "official subject-disjoint test set",
        }
        path = save_artifact(
            name=f"uci_har_baseline_{name}",
            model=model,
            task="activity_public_benchmark",
            model_type=type(model).__name__,
            metrics=metrics,
            config={"model": name, "params": model.get_params()},
            dataset=uci_har.manifest(),
            input_spec={"kind": "uci_har_561_features", "deployable": False},
            classes=classes,
            deployable=False,
            # UCI's own 561-feature pipeline, not RehabSense's: the backend
            # refuses this bundle by version, as it should.
            feature_version="uci-har-561-external",
            preprocessing_version="uci-har-external",
            validation_status={"public_dataset": "EVALUATED (official subject-disjoint split)",
                               "rehabsense_hardware": "NOT_APPLICABLE (not deployable)",
                               "clinical": "NOT_VALIDATED"},
        )
        print(f"{name}: acc {metrics['accuracy']} macroF1 {metrics['macro_f1']} -> {path}")


if __name__ == "__main__":
    main()
