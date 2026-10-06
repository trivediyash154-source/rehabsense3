"""Replay real public recordings through the complete device pipeline.

    backend/.venv/bin/python ml/scripts/replay_through_device_pipeline.py   (needs backend deps)

For each Daily & Sports subject: a standing segment is the calibration still
phase, then labelled activity segments follow, all re-expressed as protocol-v2
DualSamples (100 Hz, MPU6050 quantisation, timestamp jitter) and fed to the
production DualSessionProcessor -- calibration, bias correction, buffering,
windowing, prepare_model_input, features, model -- exactly as an ESP32 stream
would be. Measures how often the activity reported by the device pipeline
matches the recording's label.

This verifies that the hardware path feeds the model correctly. It is still
public data (the model has seen these subjects in training), so it is NOT a
generalisation or hardware-accuracy figure.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rehabsense_ml  # noqa: E402,F401
import numpy as np  # noqa: E402

from app.hardware.protocol_v2 import DualSample, HelloV2  # noqa: E402
from app.sensing.processor import DualSessionProcessor  # noqa: E402
from rehabsense_ml import ARTIFACT_DIR, REPORT_DIR  # noqa: E402
from rehabsense_ml.datasets import daily_sports  # noqa: E402

ACT = {"a01": "sitting", "a09": "walking", "a12": "running", "a05": "stairs_up",
       "a15": "cycling", "a03": "lying"}


def to_device(block25: np.ndarray, t0: float, rng) -> tuple[np.ndarray, np.ndarray]:
    t25 = t0 + np.arange(len(block25)) / 25.0
    t100 = np.arange(t25[0], t25[-1] + 0.04 - 1e-9, 0.01)
    up = np.column_stack([np.interp(t100, t25, c) for c in block25.T])
    up[:, [0, 1, 2, 6, 7, 8]] = np.clip(np.round(up[:, [0, 1, 2, 6, 7, 8]] * 8192) / 8192, -4, 4)
    up[:, [3, 4, 5, 9, 10, 11]] = np.clip(np.round(up[:, [3, 4, 5, 9, 10, 11]] * 65.5) / 65.5, -500, 500)
    return t100 + rng.normal(0, 0.0005, len(t100)), up


def main() -> None:
    import os

    os.environ.setdefault("ML_MODEL_DIR", str(ARTIFACT_DIR))
    recs = daily_sports._load_all()
    rng = np.random.default_rng(0)
    by_key = {(r.subject, r.source_activity, r.meta["segment"]): r for r in recs}
    hello = HelloV2(protocol_version=2, device_id="replay", sample_rate_hz=100, simulated=True,
                    data_source="PUBLIC_DATASET_REPLAY",
                    imus=[{"side": "LEFT", "placement": "SHANK"}, {"side": "RIGHT", "placement": "SHANK"}])
    results = {}
    total = Counter()
    for subject in sorted({r.subject for r in recs}):
        proc = DualSessionProcessor(0, "WALK", hello, provenance="PUBLIC_DATASET_REPLAY")
        proc.on_connect(hello)
        # still phase (standing, 2 segments = 10 s covers still + movement windows)
        plan = [("a02", 2), ("a02", 3)]
        plan += [(a, s) for a in ACT for s in range(10, 14)]
        t, seq, spans = 0.0, 0, []
        for act, seg in plan:
            r = by_key[(subject, act, seg)]
            ts, dev = to_device(np.column_stack([r.left, r.right]), t, rng)
            spans.append((act, ts[0], ts[-1]))
            for k in range(0, len(ts), 10):
                samples = [DualSample(ts=float(ts[i]), seq=seq + i - k if False else seq + (i - k),
                                      imu_left=dict(zip(("ax", "ay", "az", "gx", "gy", "gz"), dev[i, 0:6])),
                                      imu_right=dict(zip(("ax", "ay", "az", "gx", "gy", "gz"), dev[i, 6:12])))
                           for i in range(k, min(len(ts), k + 10))]
                for e in proc.process(samples, arrival=1000 + float(ts[k])):
                    if e.type == "activity_result":
                        mid = (e.payload["t_start"] + e.payload["t_end"]) / 2 + proc.t0
                        true = next((a for a, s0, s1 in spans
                                     if s0 <= e.payload["t_start"] + proc.t0 and e.payload["t_end"] + proc.t0 <= s1), None)
                        if true in ACT:
                            key = "correct" if e.payload.get("activity") == ACT[true] else \
                                  ("low_conf" if e.payload["status"] != "OK" else "wrong")
                            total[key] += 1
                            results.setdefault(ACT[true], Counter())[key] += 1
                        del mid
                seq += len(samples)
            t = float(ts[-1]) + 0.01
    out = {
        "provenance": "PUBLIC_DATASET_REPLAY",
        "windows_scored": sum(total.values()),
        "agreement_with_label": round(total["correct"] / max(1, sum(total.values())), 4),
        "by_activity": {k: dict(v) for k, v in results.items()},
        "scope": "Device-pipeline integrity on replayed public recordings (seen in training). "
                 "Not a generalisation estimate and NOT hardware validation.",
    }
    (REPORT_DIR / "device_pipeline_replay.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
