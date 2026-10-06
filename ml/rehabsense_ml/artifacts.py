"""Versioned training artifacts. Never overwritten.

Every run writes a new directory `ml/artifacts/<name>/v<N>/` (N = previous
highest + 1, created atomically with mkdir) containing:

    bundle.json            the contract the backend checks before loading
    model.joblib           the estimator
    metrics.json           evaluation results
    confusion_matrix.csv   labelled confusion matrix
    config.json            training configuration and hyperparameters
    dataset_manifest.json  dataset identity (archive hashes), exclusions
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn

from app.sensing.features import FEATURE_VERSION
from app.sensing.windowing import PREPROCESSING_VERSION
from rehabsense_ml import ARTIFACT_DIR, ROOT


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def _git_dirty() -> bool | None:
    try:
        out = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"],
                                      stderr=subprocess.DEVNULL, text=True)
        return bool(out.strip())
    except Exception:
        return None


def next_version_dir(name: str) -> Path:
    base = ARTIFACT_DIR / name
    base.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name[1:]) for p in base.iterdir()
                if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit()]
    n = max(existing, default=0) + 1
    while True:
        d = base / f"v{n}"
        try:
            d.mkdir()          # fails if it exists: never overwrite
            return d
        except FileExistsError:
            n += 1


def save_artifact(*, name: str, model, task: str, model_type: str, metrics: dict, config: dict,
                  dataset: dict, input_spec: dict, classes: list[str],
                  confidence_threshold: float | None = None, deployable: bool = True,
                  validation_status: dict | None = None, feature_version: str = FEATURE_VERSION,
                  preprocessing_version: str = PREPROCESSING_VERSION) -> Path:
    d = next_version_dir(name)
    model_path = d / "model.joblib"
    joblib.dump(model, model_path, compress=3)
    sha = hashlib.sha256(model_path.read_bytes()).hexdigest()

    cm = metrics.get("confusion_matrix")
    if cm:
        with open(d / "confusion_matrix.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["true\\pred"] + list(metrics["classes"]))
            for c, row in zip(metrics["classes"], cm):
                w.writerow([c] + row)

    meta = {
        "name": name,
        "version": d.name,
        "task": task,
        "model_type": model_type,
        "model_file": "model.joblib",
        "model_sha256": sha,
        "feature_version": feature_version,
        "preprocessing_version": preprocessing_version,
        "sklearn_version": sklearn.__version__,
        "input": input_spec,
        "classes": classes,
        "confidence_threshold": confidence_threshold,
        "deployable": deployable,
        "dataset": {"name": dataset.get("name"), "sensor": dataset.get("sensor"),
                    "placements": dataset.get("placements", [])},
        "metrics_summary": {k: metrics.get(k) for k in ("accuracy", "macro_f1")},
        "validation_status": validation_status or {
            "public_dataset": "EVALUATED (subject-independent; see metrics.json)",
            "rehabsense_hardware": "NOT_VALIDATED",
            "clinical": "NOT_VALIDATED",
        },
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "host": {"platform": platform.platform(), "python": platform.python_version()},
    }
    (d / "bundle.json").write_text(json.dumps(meta, indent=2))
    (d / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (d / "config.json").write_text(json.dumps(config, indent=2, default=str))
    (d / "dataset_manifest.json").write_text(json.dumps(dataset, indent=2))
    return d
