"""Recompute a stored calibration from the session's raw chunks and compare.

    cd backend && python -m scripts.recompute_calibration <session_id> [sequence]

Reproducibility check: the stored record names the exact sample windows it
used; re-running the same code on the same stored samples must give the
same per-sensor offsets and orientation (to float32 storage precision).
"""

from __future__ import annotations

import json
import sys

import numpy as np

from app.db.database import SessionLocal
from app.db.models.sensing import DeviceCalibration
from app.sensing.calibration import recompute
from app.sensing.channels import ChannelLayout
from app.services import sensing_service


def compare(session_id: int, sequence: int = 1) -> dict:
    db = SessionLocal()
    try:
        row = db.query(DeviceCalibration).filter_by(session_id=session_id, sequence=sequence).one()
        meta = row.payload
        columns, data = sensing_service.session_samples(db, session_id)
    finally:
        db.close()
    force_ids = tuple(meta["force_offset"].keys())     # declared order, as calibrated
    layout = ChannelLayout(force_ids=force_ids,
                           force_sides=tuple(None for _ in force_ids),
                           force_units=tuple(meta["force_offset"][f]["unit"] for f in force_ids),
                           imu_sides=tuple(s for s in ("LEFT", "RIGHT")
                                           if not np.isnan(data[:, 2 + (0 if s == "LEFT" else 6)]).all()))
    cal = recompute(layout, meta["sampling_rate"]["declared_hz"], data[:, 0].astype(float),
                    data[:, 2:].astype(float), meta["windows"], meta["sampling_rate"]["measured_hz"],
                    still_seconds=meta["protocol"]["still_seconds"],
                    movement_seconds=meta["protocol"]["movement_seconds"])
    again = cal.metadata()
    diffs = {}
    for side in ("left", "right"):
        a, b = meta[f"{side}_imu_offset"], again[f"{side}_imu_offset"]
        for key in ("gyro_bias_dps", "neutral_gravity_unit", "rotation_axis_unit"):
            if a[key] is not None and b[key] is not None:
                diffs[f"{side}.{key}"] = float(np.max(np.abs(np.subtract(a[key], b[key]))))
            elif (a[key] is None) != (b[key] is None):
                diffs[f"{side}.{key}"] = float("inf")
    return {"session_id": session_id, "sequence": sequence, "status_stored": meta["status"],
            "status_recomputed": again["status"], "max_abs_differences": diffs}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(json.dumps(compare(int(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 1), indent=2))
