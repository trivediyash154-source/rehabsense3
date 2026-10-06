"""Model bundles and activity inference.

A *bundle* is a directory produced by `ml/` training, never overwritten:

    <ML_MODEL_DIR>/<name>/v<N>/
        bundle.json          contract: input, classes, versions, domain, hashes
        model.joblib         the estimator (scikit-learn API)
        metrics.json, confusion_matrix.csv, config.json, dataset_manifest.json

The backend refuses a bundle when:
  * its feature_version / preprocessing_version differ from this code's,
    because the model would be fed features it was not trained on;
  * the model file's SHA-256 differs from bundle.json, because joblib files
    are pickles and must only ever be loaded from a verified artifact;
  * the scikit-learn major.minor it was trained with is not the installed one.

Every prediction carries a status and a confidence, and a domain block that
says what the model was trained on and that it has NOT been validated on
RehabSense hardware. A low-probability prediction is reported as
LOW_CONFIDENCE, not dressed up as an answer.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.sensing import features as F
from app.sensing.windowing import MAX_MISSING_FRACTION, PREPROCESSING_VERSION, prepare_model_input


class BundleError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ModelBundle:
    path: Path
    meta: dict
    model: object

    @property
    def name(self) -> str:
        return self.meta["name"]

    @property
    def version(self) -> str:
        return self.meta["version"]

    @property
    def input_kind(self) -> str:
        return self.meta["input"]["kind"]  # "bilateral" | "single_side"

    @property
    def rate_hz(self) -> float:
        return float(self.meta["input"]["rate_hz"])

    @property
    def window_s(self) -> float:
        return float(self.meta["input"]["window_s"])

    @property
    def classes(self) -> list[str]:
        return list(self.meta["classes"])

    @property
    def threshold(self) -> float:
        return float(self.meta.get("confidence_threshold", 0.6))

    @classmethod
    def load(cls, path: str | Path) -> "ModelBundle":
        path = Path(path)
        meta_path = path / "bundle.json"
        if not meta_path.is_file():
            raise BundleError(f"no bundle.json in {path}")
        meta = json.loads(meta_path.read_text())
        if meta.get("feature_version") != F.FEATURE_VERSION:
            raise BundleError(
                f"bundle feature_version {meta.get('feature_version')!r} != "
                f"backend {F.FEATURE_VERSION!r}"
            )
        if meta.get("preprocessing_version") != PREPROCESSING_VERSION:
            raise BundleError(
                f"bundle preprocessing_version {meta.get('preprocessing_version')!r} != "
                f"backend {PREPROCESSING_VERSION!r}"
            )
        model_file = path / meta["model_file"]
        if sha256_file(model_file) != meta["model_sha256"]:
            raise BundleError("model file hash does not match bundle.json; refusing to load")
        try:
            import joblib
            import sklearn
        except ImportError as exc:  # pragma: no cover - environment
            raise BundleError("scikit-learn is not installed in the backend environment") from exc
        trained = str(meta.get("sklearn_version", ""))
        if trained.split(".")[:2] != sklearn.__version__.split(".")[:2]:
            raise BundleError(
                f"bundle trained with scikit-learn {trained}, backend has {sklearn.__version__}"
            )
        model = joblib.load(model_file)
        # One window at a time: a thread pool per predict costs more than the
        # prediction itself (measured: p95 33 ms with n_jobs=-1 vs ~10 ms).
        if hasattr(model, "n_jobs"):
            model.n_jobs = 1
        return cls(path=path, meta=meta, model=model)

    def summary(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "task": self.meta.get("task"),
            "model_type": self.meta.get("model_type"),
            "input": self.meta["input"],
            "classes": self.classes,
            "feature_version": self.meta.get("feature_version"),
            "preprocessing_version": self.meta.get("preprocessing_version"),
            "trained_on": self.meta.get("dataset", {}).get("name"),
            "validation_status": self.meta.get("validation_status"),
            "confidence_threshold": self.threshold,
        }


def find_bundle(root: str | Path, name: str, version: str | None = None) -> Path | None:
    """Locate `<root>/<name>/<version>`, or the highest vN when version is None."""
    base = Path(root) / name
    if not base.is_dir():
        return None
    if version:
        p = base / version
        return p if p.is_dir() else None
    versions = sorted(
        (p for p in base.iterdir() if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit()),
        key=lambda p: int(p.name[1:]),
    )
    return versions[-1] if versions else None


def _domain(bundle: ModelBundle, placements: dict[str, str]) -> dict:
    trained_on = bundle.meta.get("dataset", {})
    trained_placements = set(trained_on.get("placements", []))
    actual = set(placements.values())
    return {
        "trained_on": trained_on.get("name"),
        "training_sensor": trained_on.get("sensor"),
        "training_placements": sorted(trained_placements),
        "device_placements": placements,
        "placement_match": bool(actual) and actual <= trained_placements,
        "hardware_validated": bool(
            (bundle.meta.get("validation_status") or {}).get("rehabsense_hardware") == "VALIDATED"
        ),
        "note": "Trained on a public dataset; not yet validated on RehabSense hardware.",
    }


def classify_window(bundle: ModelBundle | None, ts: np.ndarray, data: np.ndarray,
                    available: dict[str, bool], placements: dict[str, str],
                    neutral: dict[str, np.ndarray | None] | None = None) -> dict:
    """Run the activity model on one window of calibrated device data.

    `data` is (n, 12+F) at the device rate; only IMU columns are used by the
    current public-pretrained models (they have no force input, because no
    public dataset has a matching force sensor). `neutral` holds each side's
    calibrated neutral gravity direction; posture features need it, so
    without calibration there is no prediction.
    """
    neutral = neutral or {}
    if bundle is None:
        return {"status": "MODEL_UNAVAILABLE", "activity": None, "confidence": None,
                "message": "No activity model is loaded on this server."}
    t0 = time.perf_counter()
    n = int(round(bundle.window_s * bundle.rate_hz))
    t_start = float(ts[-1]) - bundle.window_s
    grid = prepare_model_input(ts, data[:, :12], bundle.rate_hz,
                               t_start=t_start + 1.0 / bundle.rate_hz, n=n)

    sides = [s for s in ("LEFT", "RIGHT") if available.get(s)]
    if bundle.input_kind == "bilateral":
        if len(sides) < 2:
            return {"status": "INSUFFICIENT_DATA", "activity": None, "confidence": None,
                    "message": "This model needs both IMUs; one is not reporting.",
                    "model": f"{bundle.name}/{bundle.version}"}
        left, right = grid[:, 0:6], grid[:, 6:12]
        if max(np.isnan(left).mean(), np.isnan(right).mean()) > MAX_MISSING_FRACTION:
            return {"status": "INSUFFICIENT_DATA", "activity": None, "confidence": None,
                    "message": "Too many missing samples in this window.",
                    "model": f"{bundle.name}/{bundle.version}"}
        if neutral.get("LEFT") is None or neutral.get("RIGHT") is None:
            return {"status": "INSUFFICIENT_DATA", "activity": None, "confidence": None,
                    "message": "Calibration required: no neutral pose recorded for both IMUs.",
                    "model": f"{bundle.name}/{bundle.version}"}
        x = F.bilateral_features(left[None], right[None], bundle.rate_hz,
                                 neutral["LEFT"], neutral["RIGHT"])
    else:
        if not sides:
            return {"status": "INSUFFICIENT_DATA", "activity": None, "confidence": None,
                    "message": "No IMU is reporting.", "model": f"{bundle.name}/{bundle.version}"}
        side = sides[0]
        block = grid[:, 0:6] if side == "LEFT" else grid[:, 6:12]
        if np.isnan(block).mean() > MAX_MISSING_FRACTION:
            return {"status": "INSUFFICIENT_DATA", "activity": None, "confidence": None,
                    "message": "Too many missing samples in this window.",
                    "model": f"{bundle.name}/{bundle.version}"}
        if neutral.get(side) is None:
            return {"status": "INSUFFICIENT_DATA", "activity": None, "confidence": None,
                    "message": "Calibration required: no neutral pose recorded.",
                    "model": f"{bundle.name}/{bundle.version}"}
        x = F.side_features(block[None], bundle.rate_hz, neutral[side])

    if np.isnan(x).any():
        x = np.nan_to_num(x)
    proba = bundle.model.predict_proba(x)[0]
    order = np.argsort(proba)[::-1]
    top, second = float(proba[order[0]]), float(proba[order[1]]) if len(order) > 1 else 0.0
    classes = [str(c) for c in bundle.model.classes_]
    latency_ms = (time.perf_counter() - t0) * 1000.0
    status = "OK" if top >= bundle.threshold else "LOW_CONFIDENCE"
    return {
        "status": status,
        "activity": classes[order[0]] if status == "OK" else None,
        "candidate": classes[order[0]],
        "confidence": round(top, 4),
        "margin": round(top - second, 4),
        "probabilities": {classes[i]: round(float(proba[i]), 4) for i in order[:5]},
        "model": f"{bundle.name}/{bundle.version}",
        "input_kind": bundle.input_kind,
        "inference_ms": round(latency_ms, 2),
        "domain": _domain(bundle, placements),
        "message": None if status == "OK" else "Low-confidence prediction",
    }
