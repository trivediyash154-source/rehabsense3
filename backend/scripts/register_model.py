"""Register a trained model bundle in the database (model_versions).

    cd backend && python -m scripts.register_model ../ml/artifacts/activity_bilateral/v1

Verifies the bundle the same way the server does before loading it (feature
and preprocessing versions, SHA-256 of the model file), then records it. A
(name, version) pair can be registered once; bundles are never overwritten.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models.audit import AuditAction
from app.db.models.sensing import ModelVersion
from app.sensing.inference import ModelBundle
from app.services import audit_service


def register(path: Path) -> int:
    bundle = ModelBundle.load(path)   # raises if the bundle fails verification
    meta = bundle.meta
    metrics = json.loads((path / "metrics.json").read_text()) if (path / "metrics.json").exists() else {}
    config = json.loads((path / "config.json").read_text()) if (path / "config.json").exists() else {}
    dataset = json.loads((path / "dataset_manifest.json").read_text()) \
        if (path / "dataset_manifest.json").exists() else meta.get("dataset", {})
    db = SessionLocal()
    try:
        exists = db.execute(select(ModelVersion).where(
            ModelVersion.name == meta["name"], ModelVersion.version == meta["version"])).scalar_one_or_none()
        if exists is not None:
            print(f"already registered: {meta['name']}/{meta['version']} (id {exists.id})")
            return exists.id
        row = ModelVersion(
            name=meta["name"], version=meta["version"], task=meta["task"],
            model_type=meta["model_type"], artifact_path=str(path.resolve()),
            model_sha256=meta["model_sha256"], feature_version=meta["feature_version"],
            preprocessing_version=meta["preprocessing_version"], dataset=dataset,
            metrics={k: metrics.get(k) for k in ("accuracy", "macro_f1", "per_class_f1",
                                                 "robustness_macro_f1", "latency_ms_p50",
                                                 "coverage_at_threshold")},
            training_config=config, validation_status=meta["validation_status"],
            trained_at=meta.get("trained_at"),
        )
        db.add(row)
        db.flush()
        audit_service.record(db, action=AuditAction.MODEL_REGISTERED, entity_type="model_version",
                             entity_id=row.id, name=row.name, version=row.version)
        db.commit()
        print(f"registered {row.name}/{row.version} as id {row.id}")
        return row.id
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    register(Path(sys.argv[1]))
