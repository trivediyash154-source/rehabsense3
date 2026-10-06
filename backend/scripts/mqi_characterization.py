"""Characterise the (unvalidated) Movement Quality Index on SIMULATED data.

    cd backend && python -m scripts.mqi_characterization

Engineering characterisation of the frozen definition (app/sensing/quality.py),
using the production DualSessionProcessor on synthetic streams:

  directionality   MQI and its symmetry component vs injected asymmetry
  noise            MQI vs sensor noise (1x .. 8x)
  missing sensors  which components drop out, and the MQI that remains
  repeatability    spread across 10 seeds of the same condition

None of this is evidence that the MQI measures movement quality in people.
Comparison against human ratings: NOT DONE (no human-rated recordings exist).
Output: ml/reports/mqi_characterization.json
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.hardware.protocol_v2 import DualSample, HelloV2
from app.sensing.processor import DualSessionProcessor
from app.sensing.quality import MQI_VERSION, definition, definition_sha256
from app.simulator.dual_imu import DualImuModel, SideConfig

OUT = Path(__file__).resolve().parents[2] / "ml" / "reports" / "mqi_characterization.json"
RATE = 100.0


def run(*, severity=0.0, noise=1.0, right=True, force=True, seed=0, seconds=50.0):
    imus = [{"side": "LEFT", "placement": "SHANK"}] + ([{"side": "RIGHT", "placement": "SHANK"}] if right else [])
    fc = [{"id": "heel_left", "side": "LEFT"}, {"id": "heel_right", "side": "RIGHT"}] if force else []
    hello = HelloV2(protocol_version=2, device_id="mqi-char", sample_rate_hz=RATE, simulated=True,
                    imus=imus, force_channels=fc)
    model = DualImuModel(exercise="SQUAT", seed=seed, left=SideConfig(severity=severity, noise_scale=noise),
                         right=SideConfig(present=right, noise_scale=noise),
                         force_sides=("LEFT", "RIGHT") if force else ())
    proc = DualSessionProcessor(0, "SQUAT", hello)
    proc.on_connect(hello)
    n = int(seconds * RATE)
    for k in range(0, n, 10):
        proc.process([DualSample(ts=i / RATE, seq=i, **model.sample(i / RATE))
                      for i in range(k, min(n, k + 10))], arrival=float(k))
    q = proc.finalize()["movement_quality"]
    return q


def stats(values):
    v = [x for x in values if x is not None]
    if not v:
        return {"n": 0}
    return {"n": len(v), "mean": round(float(np.mean(v)), 2), "sd": round(float(np.std(v)), 2),
            "min": round(float(np.min(v)), 2), "max": round(float(np.max(v)), 2)}


def main() -> None:
    res = {
        "evidence_level": "SIMULATED -- engineering characterisation only; not validation",
        "mqi_version": MQI_VERSION, "definition_sha256": definition_sha256(),
        "definition": definition(),
        "human_rating_comparison": "NOT DONE -- no human-rated recordings exist",
    }
    res["directionality_vs_asymmetry"] = {}
    for sev in (0.0, 0.2, 0.4, 0.6):
        qs = [run(severity=sev, seed=s) for s in range(3)]
        res["directionality_vs_asymmetry"][str(sev)] = {
            "mqi": stats([q["mqi"] for q in qs]),
            "symmetry_component": stats([q["components"].get("symmetry") for q in qs]),
        }
    means = [res["directionality_vs_asymmetry"][k]["mqi"]["mean"] for k in ("0.0", "0.2", "0.4", "0.6")]
    res["directionality_vs_asymmetry"]["mqi_decreases_with_asymmetry"] = all(
        b < a for a, b in zip(means, means[1:]))
    res["noise_sensitivity"] = {}
    for noise in (1.0, 2.0, 4.0, 8.0):
        qs = [run(noise=noise, seed=s) for s in range(3)]
        res["noise_sensitivity"][f"{noise}x"] = {
            "mqi": stats([q["mqi"] for q in qs]),
            "smoothness": stats([q["components"].get("smoothness") for q in qs]),
        }
    res["missing_sensors"] = {}
    for name, kw in (("both_imus_force", {}), ("right_imu_missing", {"right": False}),
                     ("no_force", {"force": False}), ("right_missing_no_force", {"right": False, "force": False})):
        q = run(**kw)
        res["missing_sensors"][name] = {"mqi": q["mqi"], "status": q["status"],
                                        "confidence": q["confidence"],
                                        "unavailable_components": q["unavailable"]}
    qs = [run(seed=s) for s in range(10)]
    st = stats([q["mqi"] for q in qs])
    st["cv_pct"] = round(100 * st["sd"] / st["mean"], 2) if st.get("mean") else None
    res["repeatability_10_seeds"] = st
    res["limitations"] = [
        "Simulator kinematics are idealised; real noise, soft-tissue motion and strap slip are absent.",
        "Equal weights are an assumption, not fitted.",
        "SPARC bounds are provisional literature-range values, not norms for this device.",
        "No comparison with human ratings; no statistical validity or reliability analysis.",
    ]
    OUT.write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
