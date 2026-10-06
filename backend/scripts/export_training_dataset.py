"""Export the hardware training set: consented PHYSICAL_REGISTERED recordings only.

    cd backend && python -m scripts.export_training_dataset --out ../ml/data/rehabsense_v1

Each eligible recording is written in the research export format
(app/sensing/export.py, deidentified: no free text, pseudonymous subject
codes) under <out>/<recording_id>/, plus a top-level manifest.json. One
format for every consumer.

Enforced here, not left to the caller:
  * provenance PHYSICAL_REGISTERED only (no flag to include anything else)
  * completed sessions with an ACTIVE MODEL_TRAINING consent
  * recordings whose integrity check FAILED are listed and excluded
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models.audit import AuditAction
from app.db.models.sensing import Recording
from app.db.models.session import Session as SessionModel, SessionStatus
from app.sensing import provenance as prov
from app.sensing.export import export_recording
from app.services import audit_service, sensing_service


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)          # never overwrite an export
    db = SessionLocal()
    exported, skipped = [], {}
    try:
        for rec in db.execute(select(Recording)).scalars():
            s = db.get(SessionModel, rec.session_id)
            reason = None
            if rec.provenance != prov.PHYSICAL_REGISTERED:
                reason = rec.provenance
            elif s is None or s.status is not SessionStatus.COMPLETED:
                reason = "not_completed"
            elif not sensing_service.has_training_consent(db, s.patient_id):
                reason = "no_consent"
            elif rec.integrity_status == "FAIL":
                reason = "integrity_fail"
            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
                continue
            m = export_recording(db, rec.session_id, out / rec.recording_uid, deidentify=True)
            exported.append({"recording_id": rec.recording_uid, "dir": rec.recording_uid,
                             "subject": m and json.loads((out / rec.recording_uid / "metadata.json")
                                                         .read_text())["pseudonymous_subject_code"],
                             "samples": m["sample_counts"]["samples.npz"]})
        (out / "manifest.json").write_text(json.dumps({
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provenance_included": [prov.PHYSICAL_REGISTERED],
            "recordings": exported, "skipped": skipped,
            "split_rule": "split by subject only",
        }, indent=2))
        audit_service.record(db, action=AuditAction.DATASET_EXPORTED, entity_type="training_set",
                             entity_id=out.name, recordings=len(exported), skipped=skipped)
        db.commit()
        print(f"exported {len(exported)} recordings to {out}; skipped {skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
