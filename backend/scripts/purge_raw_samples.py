"""Raw-sample retention job. Run daily (cron / scheduler).

    cd backend && python -m scripts.purge_raw_samples

Deletes raw sensor chunks past their expiry (RAW_SAMPLE_RETENTION_DAYS) unless
they are retained for training under an active consent.
"""

from __future__ import annotations

from app.db.database import SessionLocal
from app.services.sensing_service import purge_expired_chunks


def main() -> None:
    db = SessionLocal()
    try:
        n = purge_expired_chunks(db)
        db.commit()
        print(f"deleted {n} expired raw sample chunks")
    finally:
        db.close()


if __name__ == "__main__":
    main()
