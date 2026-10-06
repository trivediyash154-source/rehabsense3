"""Generate docs/PHYSICAL_VALIDATION_REPORT.md from a real recording.

    cd backend && python -m scripts.physical_validation_report <session_id> [observations.json]

Only for a PHYSICAL_REGISTERED recording (registered ESP32, authenticated).
`observations.json` holds what only a person can observe, e.g.
  {"device.i2c_scan_0x68_0x69": {"result": "PASS", "evidence": "serial log 2026-10-07 10:02"},
   "frontend.left_status_visible": {"result": "PASS", "evidence": "screenshot fe-01.png"}}
Items without evidence are NOT TESTED. Never overwrites an existing report:
a second report is written next to it with the recording id in its name.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.db.database import SessionLocal
from app.sensing.physical_report import build, to_markdown

DOCS = Path(__file__).resolve().parents[2] / "docs"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    obs = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else {}
    db = SessionLocal()
    try:
        try:
            report = build(db, int(sys.argv[1]), obs)
        except ValueError as exc:
            raise SystemExit(f"refused: {exc}")
        db.commit()
    finally:
        db.close()
    out = DOCS / "PHYSICAL_VALIDATION_REPORT.md"
    if out.exists():
        out = DOCS / f"PHYSICAL_VALIDATION_REPORT_{report['recording_id']}.md"
    out.write_text(to_markdown(report))
    (out.with_suffix(".json")).write_text(json.dumps(report, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
