"""Hardware-data validation: is this recording usable as RehabSense data?

Applies fixed, documented thresholds to what the stream monitor and the
calibrator measured, and returns PASS / WARN / FAIL per check plus a verdict.
It answers a data-quality question only -- "were the sensors, timing and
values sound?" -- never a model-accuracy or clinical question.

A SIMULATED or UNVERIFIED recording can pass every check and is still not
hardware evidence: only a registered device authenticated with its own key
counts. Simulator results are reported separately, always.
"""

from __future__ import annotations

VALIDATION_VERSION = "hw-validate-v1"

THRESHOLDS = {
    "loss_pass": 0.02, "loss_warn": 0.10,
    "rate_pass": 0.05, "rate_warn": 0.15,
    "drift_ppm_warn": 500.0,
    "dup_ooo_warn": 0.01,
    "availability_pass": 0.98, "availability_warn": 0.90,
    "saturation_warn": 0.01,
}


def _status(value, pass_max, warn_max):
    if value is None:
        return "SKIPPED"
    return "PASS" if value <= pass_max else "WARN" if value <= warn_max else "FAIL"


from app.sensing import provenance as prov  # noqa: E402


def assess(stream: dict, calibration: dict | None, *, provenance: str,
           disconnects: int = 0, imu_sides: list[str] | None = None) -> dict:
    T = THRESHOLDS
    checks = []

    def add(key, status, value, message):
        checks.append({"key": key, "status": status, "value": value, "message": message})

    accepted = max(1, stream.get("samples_accepted", 0))
    loss = stream.get("loss_ratio")
    add("missing_samples", _status(loss, T["loss_pass"], T["loss_warn"]), loss,
        f"{stream.get('missing_samples', 0)} samples lost in {stream.get('gaps', 0)} gaps")

    declared, measured = stream.get("declared_rate_hz"), stream.get("measured_rate_hz")
    rate_err = None if not (declared and measured) else abs(measured - declared) / declared
    add("sampling_rate", _status(rate_err, T["rate_pass"], T["rate_warn"]), measured,
        f"measured {measured} Hz vs declared {declared} Hz")

    drift = stream.get("clock_drift_ppm")
    add("timestamp_drift",
        "SKIPPED" if drift is None else ("PASS" if abs(drift) <= T["drift_ppm_warn"] else "WARN"),
        drift, "needs >= 30 s of real-time streaming" if drift is None
        else f"device clock {drift:+.0f} ppm vs server")

    dup = (stream.get("duplicates", 0) + stream.get("out_of_order", 0) +
           stream.get("timestamp_anomalies", 0)) / accepted
    add("ordering_and_duplicates", "PASS" if dup <= T["dup_ooo_warn"] else "WARN", round(dup, 4),
        f"{stream.get('duplicates', 0)} duplicates, {stream.get('out_of_order', 0)} out of order, "
        f"{stream.get('timestamp_anomalies', 0)} non-advancing timestamps")

    declared = imu_sides or ["LEFT", "RIGHT"]
    for side in ("LEFT", "RIGHT"):
        if side not in declared:
            add(f"{side}_IMU_UNAVAILABLE".lower(), "FAIL", None,
                f"{side}_IMU_UNAVAILABLE: not declared by the device -- no bilateral analysis")
            continue
        avail = stream.get(f"{side.lower()}_available_ratio")
        status = ("FAIL" if avail is None or avail < T["availability_warn"]
                  else "PASS" if avail >= T["availability_pass"] else "WARN")
        add(f"{side.lower()}_imu_connected", status, avail,
            (f"{side} IMU delivered {avail:.1%} of samples" if avail is not None
             else f"{side} IMU never reported")
            + (f" -- {side}_IMU_UNAVAILABLE" if status == "FAIL" else ""))
        if stream.get(f"{side.lower()}_frozen"):
            add(f"{side.lower()}_imu_frozen", "FAIL", True, f"{side} IMU repeated one reading (hung bus)")
        sat = (stream.get("saturated_samples") or {}).get(side, 0) / accepted
        oor = (stream.get("out_of_range_samples") or {}).get(side, 0)
        add(f"{side.lower()}_abnormal_values",
            "FAIL" if oor else ("WARN" if sat > T["saturation_warn"] else "PASS"),
            {"saturated_ratio": round(sat, 4), "out_of_range": oor},
            f"{oor} impossible readings, {sat:.2%} at full scale")

    if stream.get("force_out_of_range"):
        add("force_abnormal_values", "FAIL", stream["force_out_of_range"],
            "force readings outside the 0-1 ADC range")

    add("disconnects", "PASS" if disconnects == 0 else "WARN", disconnects,
        f"device disconnected {disconnects} time(s)")

    if calibration is None:
        add("calibration", "FAIL", None, "no calibration recorded")
    elif calibration.get("stale_reason"):
        add("calibration", "WARN", calibration.get("quality"),
            f"calibration {calibration.get('status')} but stale: {calibration['stale_reason']}")
    else:
        add("calibration", calibration.get("status", "FAIL"), calibration.get("quality"),
            f"calibration {calibration.get('status')} (quality {calibration.get('quality')})"
            + (f" -- {calibration['failure_reason']}" if calibration.get("failure_reason") else ""))

    statuses = [c["status"] for c in checks]
    verdict = ("NOT_USABLE" if "FAIL" in statuses
               else "USABLE_WITH_WARNINGS" if "WARN" in statuses else "USABLE")
    return {
        "version": VALIDATION_VERSION,
        "verdict": verdict,
        "data_source": provenance,
        "evidence_level": prov.DESCRIPTION.get(provenance, prov.DESCRIPTION[prov.PHYSICAL_UNVERIFIED]),
        "counts_as_hardware_evidence": prov.counts_as_physical_evidence(provenance),
        "checks": checks,
        "thresholds": THRESHOLDS,
        "scope": "Data quality only. Says nothing about model accuracy or clinical validity.",
    }
