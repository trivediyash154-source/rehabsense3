"""First physical validation report, built only from recorded evidence.

Every item is PASS, FAIL or NOT TESTED, and every PASS/FAIL cites the stored
evidence it was computed from (recording id, calibration id, counters). An
item with no evidence is NOT TESTED -- never PASS because the code "looks
right". Items the backend cannot observe (what the frontend displayed, what
the serial log said) come only from an operator observations file.

Refuses to build a report for anything but a PHYSICAL_REGISTERED recording.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.sensing import provenance as prov

PASS, FAIL, NOT_TESTED = "PASS", "FAIL", "NOT TESTED"

OBSERVABLE_ONLY_BY_OPERATOR = [
    "frontend.left_status_visible", "frontend.right_status_visible", "frontend.force_status_visible",
    "frontend.sampling_metrics_visible", "frontend.calibration_state_visible",
    "frontend.recording_state_visible", "frontend.no_simulated_values_as_physical",
    "device.boots", "device.i2c_scan_0x68_0x69", "left.values_change_when_moved",
    "right.values_change_when_moved", "force.adc_responds_to_load", "force.saturation_checked",
]


def _git() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def build(db, session_id: int, observations: dict | None = None) -> dict:
    from app.db.models.sensing import DeviceCalibration, Recording
    from app.services import sensing_service

    rec = db.execute(select(Recording).where(Recording.session_id == session_id)).scalar_one_or_none()
    if rec is None:
        raise ValueError("no protocol-v2 recording for this session")
    if rec.provenance != prov.PHYSICAL_REGISTERED:
        raise ValueError(f"provenance is {rec.provenance}: a physical validation report needs "
                         "a PHYSICAL_REGISTERED recording (registered device, authenticated)")
    if rec.metadata_json is None:
        sensing_service.finalize_recording(db, session_id)
    meta, integ = rec.metadata_json or {}, rec.integrity or {"checks": []}
    checks = {c["key"]: c for c in integ.get("checks", [])}
    cals = list(db.execute(select(DeviceCalibration).where(DeviceCalibration.session_id == session_id)
                           .order_by(DeviceCalibration.sequence)).scalars())
    valid = [c for c in cals if c.invalidated_at is None]
    imus = {i["side"]: i for i in (rec.sampling_config or {}).get("imus", [])}
    avail = meta.get("availability") or {}
    sampling = meta.get("sampling") or {}
    packets = meta.get("packets") or {}
    obs = observations or {}
    ref = f"recording {rec.recording_uid}"
    items: dict[str, tuple[str, str]] = {}

    items["connection"] = (PASS if (meta.get("duration_s") or 0) > 0 else FAIL,
                           f"{ref}: {meta.get('duration_s')} s of samples stored")
    items["authentication"] = (PASS, f"{ref}: provenance PHYSICAL_REGISTERED (device "
                                     f"{rec.device_id} authenticated with its registered key)")
    if valid:
        c = valid[-1]
        items["calibration"] = (PASS if c.status.value in ("PASS", "WARN") else FAIL,
                                f"calibration {c.id} (#{c.sequence}): {c.status.value}, "
                                f"quality {c.quality}")
    else:
        items["calibration"] = (FAIL if cals else NOT_TESTED, "no valid calibration stored")
    req, eff = sampling.get("requested_rate_hz"), sampling.get("effective_rate_hz")
    if req and eff:
        err = abs(eff - req) / req
        items["sampling"] = (PASS if err <= 0.05 else FAIL,
                             f"requested {req} Hz, observed (median interval) "
                             f"{sampling.get('observed_rate_hz_median_interval')} Hz, effective {eff} Hz "
                             f"({err:.2%} from requested)")
    else:
        items["sampling"] = (NOT_TESTED, "no rate measurement")
    ms = packets.get("missing_samples")
    if ms is not None:
        loss = ms / max(1, ms + int(round((meta.get("duration_s") or 0) * (eff or 0))))
        items["packet_loss"] = (PASS if loss <= 0.02 else FAIL,
                                f"{ms} samples missing in {packets.get('sequence_gaps')} gaps ({loss:.3%}); "
                                f"{packets.get('duplicate_packets_dropped')} duplicates dropped")
    else:
        items["packet_loss"] = (NOT_TESTED, "no packet accounting")
    ts_ok = [checks.get(k) for k in ("sequence_strictly_increasing", "timestamps_strictly_increasing")]
    items["timestamp_integrity"] = (
        NOT_TESTED if None in ts_ok else PASS if all(c["status"] == "PASS" for c in ts_ok) else FAIL,
        "; ".join(f"{c['key']}: {c['detail']}" for c in ts_ok if c))
    for side in ("LEFT", "RIGHT"):
        d = imus.get(side)
        a = avail.get(side)
        if d is None:
            items[f"{side.lower()}_sensor"] = (FAIL, f"{side} IMU not declared by the device "
                                                      f"({side}_IMU_UNAVAILABLE)")
            continue
        who_ok = d.get("who_am_i") is not None and d.get("config_readback_ok") is True
        ok = who_ok and a is not None and a >= 0.98
        items[f"{side.lower()}_sensor"] = (
            PASS if ok else FAIL,
            f"addr {d.get('i2c_address')}, WHO_AM_I {d.get('who_am_i')}, config read-back "
            f"{d.get('config_readback_ok')}, availability {a}")
    fch = (rec.sampling_config or {}).get("force_channels") or []
    if not fch:
        items["force"] = (NOT_TESTED, "device declared no force channels")
    else:
        fa = avail.get("force") or {}
        cal_force = (valid[-1].payload.get("checks") if valid else []) or []
        fcheck = next((c for c in cal_force if c["key"] == "force_sensor"), None)
        ok = fa and all(v >= 0.98 for v in fa.values()) and fcheck and fcheck["status"] == "PASS"
        items["force"] = (PASS if ok else FAIL,
                          f"availability {fa}; calibration force check "
                          f"{None if fcheck is None else fcheck['status']} "
                          f"({None if fcheck is None else fcheck['message']}); units "
                          f"{[c.get('unit') for c in fch]} (adc_norm = raw ADC/4095, not force)")
    items["recording"] = (PASS if rec.integrity_status == "PASS" else FAIL,
                          f"{ref}: integrity {rec.integrity_status}")
    chunks = sensing_service.session_chunks(db, session_id)
    stored = sum(c.n_samples for c in chunks)
    items["database"] = (PASS if stored and chunks else FAIL,
                         f"{len(chunks)} raw chunks, {stored} samples in sensor_sample_chunks")
    fe = [k for k in OBSERVABLE_ONLY_BY_OPERATOR if k.startswith("frontend.")]
    seen = [obs[k] for k in fe if k in obs]
    if not seen:
        items["frontend"] = (NOT_TESTED, "no operator observation recorded")
    else:
        bad = [k for k in fe if k in obs and obs[k].get("result") != PASS]
        missing = [k for k in fe if k not in obs]
        items["frontend"] = (FAIL if bad else NOT_TESTED if missing else PASS,
                             "; ".join(f"{k}: {obs[k]['result']} ({obs[k].get('evidence', '')})"
                                       for k in fe if k in obs)
                             + (f"; not observed: {missing}" if missing else ""))
    operator = {k: (obs[k]["result"], obs[k].get("evidence", "")) if k in obs else (NOT_TESTED, "")
                for k in OBSERVABLE_ONLY_BY_OPERATOR if not k.startswith("frontend.")}

    pkg = json.loads((Path(__file__).resolve().parents[3] / "package.json").read_text())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_id": session_id, "recording_id": rec.recording_uid,
        "hardware": {
            "esp32": rec.device_id, "firmware_version": rec.firmware_version,
            "left_mpu6050": imus.get("LEFT"), "right_mpu6050": imus.get("RIGHT"),
            "force_hardware": fch,
        },
        "software": {
            "backend_version": _git(), "frontend_version": pkg.get("version"),
            "protocol_version": rec.protocol_version,
            "ml_version": (meta.get("model_versions") or [None])[0],
        },
        "results": {k: {"status": v[0], "evidence": v[1]} for k, v in items.items()},
        "operator_observations": {k: {"status": v[0], "evidence": v[1]} for k, v in operator.items()},
        "physically_validated_scope": "Only items marked PASS, for this device and this recording.",
    }


def to_markdown(r: dict) -> str:
    h, s = r["hardware"], r["software"]

    def imu(d):
        if not d:
            return "not declared"
        return (f"{d.get('i2c_address')} WHO_AM_I {d.get('who_am_i')} "
                f"config read-back {d.get('config_readback_ok')} ({d.get('placement')})")

    lines = [
        "# RehabSense physical validation report", "",
        f"Generated {r['generated_at']} from session {r['session_id']}, recording "
        f"`{r['recording_id']}`. Every result cites stored evidence; no evidence = NOT TESTED.", "",
        "## Hardware", "",
        f"- ESP32: `{h['esp32']}`", f"- firmware version: `{h['firmware_version']}`",
        f"- LEFT MPU6050: {imu(h['left_mpu6050'])}", f"- RIGHT MPU6050: {imu(h['right_mpu6050'])}",
        f"- force hardware: {[f.get('id') + ' (' + f.get('sensor', '') + ', ' + f.get('unit', '') + ')' for f in h['force_hardware']] or 'none declared'}",
        "", "## Software", "",
        f"- backend version: `{s['backend_version']}`", f"- frontend version: `{s['frontend_version']}`",
        f"- protocol version: `{s['protocol_version']}`", f"- ML version: `{s['ml_version']}`",
        "", "## Results", "", "| Item | Result | Evidence |", "|---|---|---|",
    ]
    for k, v in r["results"].items():
        lines.append(f"| {k.replace('_', ' ')} | **{v['status']}** | {v['evidence']} |")
    lines += ["", "## Operator-only observations", "", "| Item | Result | Evidence |", "|---|---|---|"]
    for k, v in r["operator_observations"].items():
        lines.append(f"| {k} | **{v['status']}** | {v['evidence']} |")
    lines += ["", f"Scope: {r['physically_validated_scope']} No movement-model accuracy or clinical "
              "claim follows from this report.", ""]
    return "\n".join(lines)
