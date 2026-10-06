"""RehabSense ML: public-dataset pretraining and baselines.

Feature extraction and resampling are imported from the backend
(`backend/app/sensing/features.py`, `windowing.py`), so every model trained
here sees exactly the inputs the server computes at inference time.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ML_DIR = ROOT / "ml"
BACKEND_DIR = ROOT / "backend"
RAW_DIR = ML_DIR / "data" / "raw"
CACHE_DIR = ML_DIR / "data" / "cache"
ARTIFACT_DIR = ML_DIR / "artifacts"
REPORT_DIR = ML_DIR / "reports"
DATASET_ZIPS = ROOT / "ml datadets"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
