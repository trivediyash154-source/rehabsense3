"""Export one recording in the research format and verify it.

    cd backend && python -m scripts.export_recording <session_id> <out_dir> [--deidentify]
    cd backend && python -m scripts.export_recording --verify <export_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.db.database import SessionLocal
from app.sensing.export import export_recording, verify_export

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--verify":
        print(json.dumps(verify_export(Path(sys.argv[2])), indent=2))
    elif len(sys.argv) >= 3:
        db = SessionLocal()
        try:
            m = export_recording(db, int(sys.argv[1]), Path(sys.argv[2]),
                                 deidentify="--deidentify" in sys.argv)
            db.commit()
        finally:
            db.close()
        print(json.dumps(m, indent=2))
    else:
        raise SystemExit(__doc__)
