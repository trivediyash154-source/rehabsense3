"""UCI HAR (smartphone on the waist), Kaggle CSV edition.

The archive provided ("archive (23).zip") contains only train.csv/test.csv
with the 561 *pre-computed* UCI features per window, plus subject and label.
It does not contain the raw inertial signals. Consequences, stated plainly:

  * It can only be used for a feature-space baseline with UCI's own feature
    pipeline (stage 1). Those features cannot be computed from RehabSense
    data the same way, so a model trained here can never run on the device.
  * It is reported as a public benchmark and nothing more.

The official split is by subject (21 train / 9 test), which is kept.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rehabsense_ml import DATASET_ZIPS, RAW_DIR
from rehabsense_ml.datasets import file_sha256
from rehabsense_ml.labels import UCI_HAR

NAME = "UCI HAR (Kaggle CSV, 561 precomputed features)"


def load():
    root = RAW_DIR / "uci_har_kaggle"
    train = pd.read_csv(root / "train.csv")
    test = pd.read_csv(root / "test.csv")
    feats = [c for c in train.columns if c not in ("subject", "Activity")]

    def split(df):
        return (df[feats].to_numpy(dtype=np.float64),
                df["Activity"].map(UCI_HAR).to_numpy(), df["subject"].to_numpy())

    return split(train), split(test), feats


def manifest() -> dict:
    z = DATASET_ZIPS / "archive (23).zip"
    return {"name": NAME, "archive": z.name,
            "archive_sha256": file_sha256(z) if z.exists() else None,
            "split": "official subject split (train 21 subjects / test 9 subjects)",
            "raw_signals_available": False,
            "deployable_to_rehabsense": False}
