"""SIMULATOR performance of the hardware pipeline (not hardware, not clinical).

    cd backend && python -m scripts.evaluate_simulator

Runs synthetic dual-IMU streams with *known* ground truth through the exact
production processor (DualSessionProcessor, no sockets) and measures:

  * ROM-proxy error per side vs the simulated segment amplitude
  * repetition count vs simulated cycles
  * bilateral asymmetry as injected severity increases (should rise)
  * fault detection: each injected fault must be caught by validation

What this does NOT show: anything about real MPU6050s on real people. The
simulator's physics is idealised (rigid segment, perfect strap, no soft
tissue). Results go to ml/reports/simulator_evaluation.json under the
heading "simulator performance", separate from public-dataset and hardware
results.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.hardware.protocol_v2 import DualSample, HelloV2
from app.sensing.processor import DualSessionProcessor
from app.sensing.validation import assess
from app.simulator.dual_imu import PROFILES, DualImuModel, SideConfig

RATE = 100.0
DURATION = 60.0
OUT = Path(__file__).resolve().parents[2] / "ml" / "reports" / "simulator_evaluation.json"


def run(exercise: str, left_sev: float = 0.0, fault: str | None = None, seed: int = 0):
    hello = HelloV2(protocol_version=2, device_id="sim-eval", sample_rate_hz=RATE, simulated=True,
                    imus=[{"side": "LEFT", "placement": "SHANK"}, {"side": "RIGHT", "placement": "SHANK"}],
                    force_channels=[{"id": "heel_left", "side": "LEFT"},
                                    {"id": "heel_right", "side": "RIGHT"}])
    model = DualImuModel(exercise=exercise, seed=seed, left=SideConfig(severity=left_sev))
    proc = DualSessionProcessor(0, exercise, hello)
    proc.on_connect(hello)
    frozen = None
    n = int(DURATION * RATE)
    rng = np.random.default_rng(seed)
    for k in range(0, n, 10):
        if fault == "packet_loss" and rng.random() < 0.1:
            continue
        batch = []
        for i in range(k, min(n, k + 10)):
            s = model.sample(i / RATE)
            if fault == "right_dropout" and 25 * RATE <= i < 35 * RATE:
                s["imu_right"] = None
            if fault == "frozen_left" and i >= 30 * RATE:
                frozen = frozen or s["imu_left"]
                s["imu_left"] = frozen
            if fault == "impossible_value" and i == 3000:
                s["imu_right"] = {**s["imu_right"], "gx": 900.0}
            batch.append(DualSample(ts=i / RATE, seq=i, **s))
        proc.process(batch, arrival=1000.0 + k / RATE)
    summary = proc.finalize()
    return proc, model, summary


def main() -> None:
    results: dict = {
        "evidence_level": "SIMULATOR ONLY -- synthetic kinematics with known ground truth. "
                          "Not RehabSense hardware performance. Not clinical validation.",
        "created": datetime.now(timezone.utc).isoformat(),
        "rom_proxy": {}, "repetitions": {}, "asymmetry_vs_severity": {}, "fault_detection": {},
    }
    move_s = DURATION - DualImuModel().still_s - DualImuModel().calib_move_s
    for ex in ("SQUAT", "SIT_TO_STAND", "WALK", "KNEE_EXTENSION", "STEP_UP"):
        proc, model, s = run(ex)
        rs = s["repetition_summary"]
        amp = PROFILES[ex]["amp"]
        true_range = (2 * 0.8 * amp) if ex == "WALK" else amp   # walk: +-0.55/0.25 harmonic shape
        if ex == "WALK":
            # One full period well after the simulator's 1 s onset ramp.
            tt = np.linspace(10.0, 10.0 + PROFILES[ex]["period"], 500)
            true_range = float(np.ptp([model.tilt("LEFT", t) for t in tt]))
        results["rom_proxy"][ex] = {
            side: {"detected_deg": v["rom_proxy_deg_mean"], "true_deg": round(true_range, 1),
                   "error_pct": round(100 * (v["rom_proxy_deg_mean"] - true_range) / true_range, 1)}
            for side, v in rs.items()
        }
        period = PROFILES[ex]["period"]
        per_side = move_s / period / (2 if PROFILES[ex]["pattern"] == "unilateral" else 1)
        results["repetitions"][ex] = {
            "detected": {side: v["count"] for side, v in rs.items()},
            "simulated_cycles_per_side_approx": round(per_side + 5.0 * 0.6 / period, 1),
            "note": "approximate: includes the slowed calibration movement; rep detection "
                    "excludes cycles still open at the end of the session",
        }
    for ex in ("SQUAT", "WALK", "SIT_TO_STAND"):
        row = {}
        for sev in (0.0, 0.2, 0.4, 0.6):
            _, _, s = run(ex, left_sev=sev, seed=3)
            row[str(sev)] = s["bilateral"]["asymmetry_score"]
        scores = [v for v in row.values() if v is not None]
        row["monotonic_increase"] = all(b > a for a, b in zip(scores, scores[1:]))
        results["asymmetry_vs_severity"][ex] = row
    for fault, expect in (("packet_loss", "missing_samples"), ("right_dropout", "right_imu_connected"),
                          ("frozen_left", "left_imu_frozen"),
                          ("impossible_value", "right_abnormal_values")):
        proc, _, s = run("SQUAT", fault=fault)
        rep = assess(s["stream"], s["calibration"], provenance="SIMULATED")
        flagged = [c for c in rep["checks"] if c["key"] == expect and c["status"] in ("WARN", "FAIL")]
        results["fault_detection"][fault] = {"expected_check": expect, "detected": bool(flagged),
                                             "verdict": rep["verdict"]}
    OUT.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
