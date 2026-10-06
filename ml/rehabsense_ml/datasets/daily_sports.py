"""Daily and Sports Activities (Barshan & Altun, UCI ML Repository).

19 activities x 8 subjects x 60 five-second segments, 25 Hz, five Xsens MTx
units (torso, right arm, left arm, right leg, left leg), each with a 3-axis
accelerometer (m/s^2), gyroscope (rad/s) and magnetometer.

Why this dataset matters for RehabSense: it has a real IMU on *each leg*,
recorded simultaneously. That is genuine bilateral data, so it can train a
two-IMU model without inventing a second side. The sensors are not MPU6050s,
are not at the same strap position, and there is no force sensor; those gaps
are handled in docs/HARDWARE_ML_ARCHITECTURE.md, not ignored.

Column layout per line (45 values): for unit in [T, RA, LA, RL, LL]:
acc x y z, gyro x y z, mag x y z.
"""

from __future__ import annotations

import numpy as np

from rehabsense_ml import CACHE_DIR, DATASET_ZIPS, RAW_DIR
from rehabsense_ml.datasets import G, RAD2DEG, Recording, file_sha256, unit
from rehabsense_ml.labels import DAILY_SPORTS

RATE = 25.0
RL = slice(27, 33)   # right leg: acc 27-29, gyro 30-32
LL = slice(36, 42)   # left leg:  acc 36-38, gyro 39-41
NAME = "Daily and Sports Activities (UCI)"
SENSOR = "Xsens MTx (acc m/s^2 -> g, gyro rad/s -> deg/s)"
PLACEMENTS = ["LEG"]


def _convert(block: np.ndarray) -> np.ndarray:
    out = block.astype(np.float64).copy()
    out[:, 0:3] /= G
    out[:, 3:6] *= RAD2DEG
    return out


CALIBRATION_ACTIVITY = "a02"   # standing
CALIBRATION_SEGMENT = 1


def load() -> list[Recording]:
    """Recordings with each subject's neutral pose attached.

    Emulates the device calibration: per subject, standing segment s01 is the
    "calibration recording". Its mean gravity direction per leg becomes that
    subject's neutral pose, and the segment itself is removed so it is never
    trained or evaluated on.
    """
    recs = _load_all()
    neutral = {}
    for r in recs:
        if r.source_activity == CALIBRATION_ACTIVITY and r.meta["segment"] == CALIBRATION_SEGMENT:
            neutral[r.subject] = (unit(r.left[:, 0:3].mean(0)), unit(r.right[:, 0:3].mean(0)))
    out = []
    for r in recs:
        if r.source_activity == CALIBRATION_ACTIVITY and r.meta["segment"] == CALIBRATION_SEGMENT:
            continue
        r.neutral_left, r.neutral_right = neutral[r.subject]
        out.append(r)
    return out


def _load_all() -> list[Recording]:
    cache = CACHE_DIR / "daily_sports.npz"
    if cache.exists():
        # NpzFile decompresses on every key access: read each array once.
        with np.load(cache, allow_pickle=False) as z:
            arrays = {k: z[k] for k in z.files}
        return [Recording(subject=str(s), label=str(lab), source_activity=str(a), rate_hz=RATE,
                          left=arrays["left"][i], right=arrays["right"][i], meta={"segment": int(seg)})
                for i, (s, lab, a, seg) in enumerate(zip(arrays["subject"], arrays["label"],
                                                         arrays["activity"], arrays["segment"]))]
    root = RAW_DIR / "daily_sports" / "data"
    lefts, rights, subjects, labels, acts, segs = [], [], [], [], [], []
    for a in range(1, 20):
        if a not in DAILY_SPORTS:
            continue
        for p in range(1, 9):
            for s in range(1, 61):
                path = root / f"a{a:02d}" / f"p{p}" / f"s{s:02d}.txt"
                arr = np.loadtxt(path, delimiter=",")
                lefts.append(_convert(arr[:, LL]))
                rights.append(_convert(arr[:, RL]))
                subjects.append(f"ds_p{p}")
                labels.append(DAILY_SPORTS[a])
                acts.append(f"a{a:02d}")
                segs.append(s)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, left=np.stack(lefts), right=np.stack(rights),
                        subject=np.array(subjects), label=np.array(labels),
                        activity=np.array(acts), segment=np.array(segs))
    return _load_all()


def manifest() -> dict:
    z = DATASET_ZIPS / "daily+and+sports+activities.zip"
    return {
        "name": NAME, "sensor": SENSOR, "placements": PLACEMENTS, "rate_hz": RATE,
        "archive": z.name, "archive_sha256": file_sha256(z) if z.exists() else None,
        "subjects": 8, "bilateral": True, "force": False,
        "excluded_activities": {"a08": "moving around in an elevator"},
        "calibration_emulation": "per subject, standing segment a02/s01 = neutral pose; "
                                 "removed from training and evaluation",
    }
