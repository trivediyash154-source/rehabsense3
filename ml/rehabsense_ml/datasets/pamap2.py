"""PAMAP2 Physical Activity Monitoring (Reiss & Stricker, UCI).

9 subjects, 100 Hz Colibri IMUs on hand, chest and the *dominant-side ankle*.
Only the ankle IMU is used (closest to a lower-limb RehabSense placement),
which makes this a single-IMU dataset. It is used for the single-side model
and as pretraining for the per-IMU encoder; it is never mirrored into a fake
left/right pair.

Ankle columns: 37 temperature, 38-40 acc +-16 g (m/s^2), 41-43 acc +-6 g,
44-46 gyro (rad/s), 47-49 magnetometer, 50-53 orientation (invalid).
The +-16 g accelerometer is used because the +-6 g one saturates on impacts.
Wireless dropouts appear as NaN; short gaps are interpolated, long ones split
the recording.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rehabsense_ml import CACHE_DIR, DATASET_ZIPS, RAW_DIR
from rehabsense_ml.datasets import G, RAD2DEG, Recording, file_sha256, unit
from rehabsense_ml.labels import PAMAP2, PAMAP2_EXCLUDED

RATE_IN = 100.0
RATE = 25.0
NAME = "PAMAP2 Physical Activity Monitoring (UCI), ankle IMU"
SENSOR = "Colibri IMU, ankle (acc16 m/s^2 -> g, gyro rad/s -> deg/s)"
PLACEMENTS = ["ANKLE"]
MAX_GAP_SAMPLES = 25   # 0.25 s at 100 Hz


def _resample(block: np.ndarray, rate_in: float, rate_out: float) -> np.ndarray:
    """100 -> 25 Hz through the backend's own model-input path.

    `prepare_model_input` is exactly what the server applies to the live
    MPU6050 stream, so public training data and device data share one
    anti-aliasing + resampling implementation.
    """
    from app.sensing.windowing import prepare_model_input

    ts = np.arange(block.shape[0]) / rate_in
    return prepare_model_input(ts, block, rate_out)


def _runs(df: pd.DataFrame, subject: str) -> list[Recording]:
    out = []
    act = df[1].to_numpy()
    imu = df[[38, 39, 40, 44, 45, 46]].to_numpy(dtype=np.float64)
    change = np.flatnonzero(np.diff(act) != 0) + 1
    bounds = np.concatenate([[0], change, [len(act)]])
    for a, b in zip(bounds[:-1], bounds[1:]):
        aid = int(act[a])
        if aid not in PAMAP2:
            continue
        block = imu[a:b]
        nan = np.isnan(block).any(axis=1)
        idx = np.arange(len(block))
        # Split on long gaps; interpolate short ones. Gap runs from edges of
        # the NaN mask.
        edges = np.diff(np.concatenate([[0], nan.astype(np.int8), [0]]))
        gap_starts, gap_ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        pieces, start = [], 0
        for gs, ge in zip(gap_starts, gap_ends):
            if ge - gs > MAX_GAP_SAMPLES or ge == len(block):
                pieces.append((start, gs))
                start = ge
        if start < len(block):
            pieces.append((start, len(block)))
        for s, e in pieces:
            seg = block[s:e].copy()
            if len(seg) < RATE_IN * 3:
                continue
            ok = ~np.isnan(seg).any(axis=1)
            if ok.sum() < 2:
                continue
            for c in range(6):
                seg[:, c] = np.interp(idx[s:e] - s, (idx[s:e] - s)[ok], seg[ok, c])
            seg[:, 0:3] /= G
            seg[:, 3:6] *= RAD2DEG
            out.append(Recording(subject=subject, label=PAMAP2[aid], source_activity=str(aid),
                                 rate_hz=RATE, left=_resample(seg, RATE_IN, RATE),
                                 meta={"side": "dominant_ankle"}))
    return out


CALIBRATION_SECONDS = 10.0


def load() -> list[Recording]:
    """Ankle recordings with each subject's neutral pose attached.

    Emulates the device calibration: the first 10 s of each subject's first
    standing recording define the neutral pose and are cut out of the data.
    Subjects with no standing recording are dropped (cannot be calibrated).
    """
    recs = _load_all()
    n = int(CALIBRATION_SECONDS * RATE)
    neutral = {}
    out = []
    for r in recs:
        if r.label == "standing" and r.subject not in neutral and len(r.left) > n:
            neutral[r.subject] = unit(r.left[:n, 0:3].mean(0))
            r = Recording(r.subject, r.label, r.source_activity, r.rate_hz, r.left[n:], meta=r.meta)
        out.append(r)
    kept = []
    for r in out:
        if r.subject in neutral:
            r.neutral_left = neutral[r.subject]
            kept.append(r)
    return kept


def _load_all() -> list[Recording]:
    cache = CACHE_DIR / "pamap2_ankle.npz"
    if cache.exists():
        with np.load(cache, allow_pickle=False) as z:
            a = {k: z[k] for k in z.files}
        offs = a["offsets"]
        return [Recording(subject=str(a["subject"][i]), label=str(a["label"][i]),
                          source_activity=str(a["activity"][i]), rate_hz=RATE,
                          left=a["data"][offs[i]:offs[i + 1]], meta={"side": "dominant_ankle"})
                for i in range(len(offs) - 1)]
    recs: list[Recording] = []
    root = RAW_DIR / "pamap2" / "PAMAP2_Dataset" / "Protocol"
    for sid in range(101, 110):
        df = pd.read_csv(root / f"subject{sid}.dat", sep=" ", header=None, engine="c")
        recs += _runs(df, f"pamap2_{sid}")
    lens = [len(r.left) for r in recs]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, data=np.vstack([r.left for r in recs]),
                        offsets=np.concatenate([[0], np.cumsum(lens)]),
                        subject=np.array([r.subject for r in recs]),
                        label=np.array([r.label for r in recs]),
                        activity=np.array([r.source_activity for r in recs]))
    return _load_all()


def manifest() -> dict:
    z = DATASET_ZIPS / "pamap2+physical+activity+monitoring.zip"
    return {
        "name": NAME, "sensor": SENSOR, "placements": PLACEMENTS,
        "rate_hz_original": RATE_IN, "rate_hz": RATE,
        "archive": z.name,
        # The archive is 688 MB; hash the first 64 MB as an identity check.
        "archive_sha256_first64mb": file_sha256(z, 64 << 20) if z.exists() else None,
        "subjects": 9, "bilateral": False, "force": False,
        "excluded_activities": {str(k): v for k, v in PAMAP2_EXCLUDED.items()},
        "calibration_emulation": "first 10 s of each subject's first standing recording = "
                                 "neutral pose; removed from training and evaluation",
    }
