"""Offline re-validation of a stored hardware recording, from its raw chunks.

    cd backend && python -m scripts.validate_recording <session_id>

Replays the stored raw samples through the same StreamMonitor the live path
uses (gaps, rate, frozen IMUs, saturation, impossible values), then applies
the same validation thresholds. Arrival times are not stored, so clock drift
and latency are reported as SKIPPED.
"""

from __future__ import annotations

import json
import sys

import numpy as np

from app.db.database import SessionLocal
from app.db.models.sensing import DeviceCalibration
from app.db.models.session import Session as SessionModel, SessionMode
from app.sensing.stream import StreamMonitor
from app.sensing.validation import assess
from app.services import sensing_service


def main(session_id: int) -> dict:
    db = SessionLocal()
    try:
        s = db.get(SessionModel, session_id)
        if s is None:
            raise SystemExit("session not found")
        columns, data = sensing_service.session_samples(db, session_id)
        if not columns:
            raise SystemExit("no raw samples stored for this session")
        cal = db.query(DeviceCalibration).filter_by(session_id=session_id).first()
        rate = (cal.sampling_rate_declared if cal else None) or 100.0
        force_cols = [c for c in columns if c.startswith("force_")]
        mon = StreamMonitor(declared_rate_hz=rate, force_units=tuple("adc_norm" for _ in force_cols))
        ts, seq, vals = data[:, 0].astype(float), data[:, 1].astype(np.int64), data[:, 2:].astype(float)
        for i in range(0, len(ts), 10):
            mon.observe(ts[i:i + 10], seq[i:i + 10], vals[i:i + 10], arrival=float(ts[i]))
        stream = mon.as_dict()
        stream["clock_drift_ppm"] = None
        sides = [x for x in ("LEFT", "RIGHT") if not np.isnan(vals[:, 0 if x == "LEFT" else 6]).all()]
        from app.sensing import provenance as prov

        provenance = prov.of_session(s)
        report = assess(stream, None if cal is None else cal.payload,
                        provenance=provenance, imu_sides=sides)
        report["source"] = "stored raw chunks (offline)"
        return report
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(json.dumps(main(int(sys.argv[1])), indent=2))
