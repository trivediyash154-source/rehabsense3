"""Research recordings: metadata, integrity checks and the event vocabulary.

A recording is the raw evidence of what a device transmitted in one
protocol-v2 session. The stored raw chunks are never modified; everything
here *describes* or *checks* them. A failed integrity check flags the
recording -- it does not repair it.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from app.sensing import provenance as prov

SCHEMA_VERSION = "rs-recording-1.0"

MARKER_KINDS = (
    "recording_start", "recording_stop", "calibration_start", "calibration_complete",
    "exercise_start", "exercise_stop", "repetition_start", "repetition_end", "manual_label",
    "artifact", "sensor_reposition", "sensor_failure", "sensor_recovered", "note",
)
MARKER_SOURCES = ("DEVICE", "SERVER", "USER", "MODEL")
TIME_BASES = ("DEVICE_TIME", "SERVER_RECEIVE_TIME_MAPPED")

INTEGRITY_VERSION = "rs-integrity-1.0"


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sampling_config(hello, settings) -> dict:
    return {
        "requested_rate_hz": hello.sample_rate_hz,
        "imus": [i.model_dump(mode="json") for i in hello.imus],
        "force_channels": [c.model_dump(mode="json") for c in hello.force_channels],
        "analysis_window_s": settings.hw_window_s,
        "analysis_stride_s": settings.hw_stride_s,
        "calibration": {"health_s": settings.hw_calibration_health_s,
                        "still_s": settings.hw_calibration_still_s,
                        "movement_s": settings.hw_calibration_movement_s},
    }


def _availability(values: np.ndarray, names: list[str]) -> dict:
    n = max(1, len(values))
    left = names.index("left_ax")
    right = names.index("right_ax")
    out = {
        "LEFT": round(1.0 - float(np.isnan(values[:, left:left + 6]).any(axis=1).sum()) / n, 6),
        "RIGHT": round(1.0 - float(np.isnan(values[:, right:right + 6]).any(axis=1).sum()) / n, 6),
        "force": {},
    }
    for j, name in enumerate(names):
        if name.startswith("force_"):
            out["force"][name] = round(1.0 - float(np.isnan(values[:, j]).sum()) / n, 6)
    return out


def scan(chunks: list, decode) -> dict:
    """Facts about the stored raw samples, computed from the samples alone."""
    ts, seqs, vals, packets = [], [], [], []
    names = None
    for c in chunks:
        t, s, v = decode(c)
        ts.append(t)
        seqs.append(s)
        vals.append(v)
        packets += c.packet_log or []
        names = names or list(c.columns[2:])
    if not ts:
        return {"samples": 0}
    t = np.concatenate(ts)
    seq = np.concatenate(seqs)
    v = np.vstack(vals)
    d = np.diff(seq)
    dt = np.diff(t)
    gaps = d[d > 1] - 1
    return {
        "samples": int(len(t)), "names": names, "t": t, "seq": seq, "values": v,
        "packets": packets,
        "duration_s": float(t[-1] - t[0]) if len(t) > 1 else 0.0,
        "seq_first": int(seq[0]), "seq_last": int(seq[-1]),
        "seq_gaps": int(len(gaps)), "missing_samples": int(gaps.sum()),
        "seq_non_increasing": int((d <= 0).sum()),
        "t_non_increasing": int((dt <= 0).sum()),
        "median_rate_hz": float(1.0 / np.median(dt[dt > 0])) if (dt > 0).any() else None,
        "effective_rate_hz": float((len(t) - 1) / (t[-1] - t[0])) if len(t) > 1 and t[-1] > t[0] else None,
        "availability": _availability(v, names),
    }


def build_metadata(*, recording, session, scan_result: dict, summary: dict | None,
                   calibrations: list, subject_code: str | None, consent: bool) -> dict:
    s = summary or {}
    stream = s.get("stream") or {}
    calib = [c for c in calibrations if c.invalidated_at is None]
    current = calib[-1] if calib else None
    sc = recording.sampling_config or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "recording_id": recording.recording_uid,
        "session_id": session.id,
        "device_id": recording.device_id,
        "pseudonymous_subject_code": subject_code,
        "start_timestamp": _iso(recording.started_at),
        "end_timestamp": _iso(recording.ended_at),
        "duration_s": round(scan_result.get("duration_s", 0.0), 6),
        "firmware_version": recording.firmware_version,
        "protocol_version": recording.protocol_version,
        "calibration_id": None if current is None else current.id,
        "calibration_ids_all": [c.id for c in calibrations],
        "calibration_status": None if current is None else current.status.value,
        "model_versions": sorted({m for m in ((s.get("activity") or {}).get("model"),) if m}),
        "sampling": {
            "requested_rate_hz": sc.get("requested_rate_hz"),
            "observed_rate_hz_median_interval": scan_result.get("median_rate_hz"),
            "effective_rate_hz": scan_result.get("effective_rate_hz"),
            "config": sc,
        },
        "packets": {
            "received": len(scan_result.get("packets") or []),
            "duplicate_packets_dropped": stream.get("duplicates"),
            "out_of_order_dropped": stream.get("out_of_order"),
            "missing_samples": scan_result.get("missing_samples"),
            "sequence_gaps": scan_result.get("seq_gaps"),
            "note": "Duplicate and out-of-order samples were counted and dropped at ingestion; "
                    "missing samples are sequence gaps in the stored raw data.",
        },
        "availability": scan_result.get("availability"),
        "clock": stream.get("clock"),
        "recording_mode": session.recording_mode.value,
        "research_protocol": session.research_protocol,
        "consent_model_training": consent,
        "provenance": recording.provenance,
        "counts_as_physical_evidence": prov.counts_as_physical_evidence(recording.provenance),
        "provenance_description": prov.DESCRIPTION.get(recording.provenance),
        "channel_layout": scan_result.get("names"),
        "units": {"acc": "g", "gyro": "deg/s", "force": "per channel name suffix (adc_norm = raw ADC / 4095)",
                  "t": "seconds of DEVICE_TIME since the first stored sample"},
    }


def check_integrity(scan_result: dict, metadata: dict, calibrations: list,
                    imu_ranges: dict | None = None) -> dict:
    """Recompute integrity from the stored raw samples. Never modifies them."""
    checks = []

    def add(key, ok, detail, warn=False):
        checks.append({"key": key, "status": "PASS" if ok else ("WARN" if warn else "FAIL"),
                       "detail": detail})

    n = scan_result.get("samples", 0)
    add("has_samples", n > 0, f"{n} samples")
    if n:
        add("sequence_strictly_increasing", scan_result["seq_non_increasing"] == 0,
            f"{scan_result['seq_non_increasing']} non-increasing steps")
        add("timestamps_strictly_increasing", scan_result["t_non_increasing"] == 0,
            f"{scan_result['t_non_increasing']} non-increasing steps")
        loss = scan_result["missing_samples"] / max(1, n + scan_result["missing_samples"])
        add("sequence_continuity", loss <= 0.02,
            f"{scan_result['missing_samples']} missing samples in {scan_result['seq_gaps']} gaps "
            f"({loss:.4%})", warn=loss <= 0.10)
        v, names = scan_result["values"], scan_result["names"]
        ranges = imu_ranges or {"acc": 4.0, "gyro": 500.0}
        imu_cols = [i for i, nm in enumerate(names) if nm[:5] in ("left_", "right")]
        acc = [i for i in imu_cols if names[i][-2] == "a"]
        gyr = [i for i in imu_cols if names[i][-2] == "g"]
        with np.errstate(invalid="ignore"):
            impossible = int((np.abs(v[:, acc]) > 1.05 * ranges["acc"]).sum()
                             + (np.abs(v[:, gyr]) > 1.05 * ranges["gyro"]).sum())
            saturated = int((np.abs(v[:, acc]) >= 0.98 * ranges["acc"]).sum()
                            + (np.abs(v[:, gyr]) >= 0.98 * ranges["gyro"]).sum())
            force_cols = [i for i, nm in enumerate(names) if nm.endswith("_adc_norm")]
            bad_force = int(((v[:, force_cols] < -0.01) | (v[:, force_cols] > 1.01)).sum())
        add("no_impossible_values", impossible == 0 and bad_force == 0,
            f"{impossible} IMU values beyond full scale, {bad_force} force values outside 0..1")
        add("saturation", saturated <= 0.01 * n * max(1, len(acc) + len(gyr)),
            f"{saturated} values at >= 98% of full scale", warn=True)
        add("duration_consistent",
            math.isclose(metadata.get("duration_s") or 0.0, scan_result["duration_s"], abs_tol=1e-3),
            f"metadata {metadata.get('duration_s')} s vs samples {scan_result['duration_s']:.3f} s")
    valid = [c for c in calibrations if c.invalidated_at is None]
    add("calibration_valid", bool(valid) and valid[-1].status.value in ("PASS", "WARN"),
        "no valid calibration" if not valid else f"calibration {valid[-1].id}: {valid[-1].status.value}")
    add("schema_version", metadata.get("schema_version") == SCHEMA_VERSION, metadata.get("schema_version"))
    add("metadata_consistent", metadata.get("session_id") is not None
        and metadata.get("recording_id") is not None and metadata.get("device_id") is not None,
        "recording, session and device identifiers present")
    add("device_authenticated", metadata.get("provenance") == prov.PHYSICAL_REGISTERED,
        f"provenance {metadata.get('provenance')}", warn=True)
    statuses = [c["status"] for c in checks]
    return {
        "version": INTEGRITY_VERSION,
        "status": "FAIL" if "FAIL" in statuses else "PASS",
        "warnings": statuses.count("WARN"),
        "checks": checks,
        "policy": "Flagged, never repaired: the stored raw chunks are the original evidence.",
    }
