"""DualSessionProcessor — per-session state machine for hardware v2.

    packet -> stream integrity -> raw chunk (for storage)
           -> calibration (8 checks) -> bias/scale correction
           -> per-IMU tilt -> analysis buffer
           -> windows -> activity model + bilateral + force/motion + phase
           -> repetitions -> MQI
           -> events

Performs no I/O. Emits `Event`s; the registry broadcasts the ones marked
`broadcast` and persists the ones with a `persist` kind. Stage latencies are
measured here with perf_counter and reported, not estimated.

Event types (all prefixed `hw_` so a v1 dashboard can never misread them):

    hw_connection      device, IMU and force-channel availability
    hw_calibration     calibration progress, then the full check list
    hw_stream_health   rate, loss, drift, relative latency
    hw_sensor_frame    decimated live signals for charts
    hw_ml_update       activity, phase, bilateral, force/motion per window
    hw_rep             one completed repetition / gait cycle
    hw_device_status   battery, RSSI, IMU flags reported by the firmware
"""

from __future__ import annotations

import time
import zlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.sensing import model_store
from app.sensing import provenance as prov
from app.sensing.bilateral import BILATERAL_VERSION, rep_asymmetry, window_asymmetry
from app.sensing.calibration import CalPhase, DeviceCalibrator
from app.sensing.channels import ChannelLayout, samples_to_array
from app.sensing.features import FEATURE_VERSION
from app.sensing.force_motion import force_by_phase, session_force_motion, window_force_motion
from app.sensing.inference import classify_window
from app.sensing.orientation import TiltEstimator, principal_axis
from app.sensing.quality import MQI_VERSION, movement_quality
from app.sensing.repetitions import (
    DETECTOR_VERSION,
    EXERCISE_BILATERAL_MODE,
    EXERCISE_REP_MODE,
    BilateralMode,
    Rep,
    RepMode,
    current_phase,
    detect_reps,
    movement_sign,
)
from app.sensing.stream import StreamMonitor
from app.sensing.windowing import PREPROCESSING_VERSION, SlidingWindowBuffer, resample_uniform

from app.sensing.recording import MARKER_KINDS as _KINDS  # noqa: E402

PIPELINE_VERSION = "hw-v2.0"
# Raw chunk layout: zlib( t float64[n] | seq int64[n] | values float32[n, C] ).
RAW_ENCODING = "rs-raw-v2"
ANALYSIS_SECONDS = 30.0
REP_SCAN_SECONDS = 20.0


@dataclass
class Event:
    type: str
    payload: dict[str, Any]
    broadcast: bool = True
    persist: str | None = None
    seq: int = 0


@dataclass
class LatencyStats:
    window: int = 500
    values: dict = field(default_factory=dict)

    def add(self, key: str, ms: float) -> None:
        self.values.setdefault(key, deque(maxlen=self.window)).append(ms)

    def as_dict(self) -> dict:
        out = {}
        for k, v in self.values.items():
            arr = np.asarray(v)
            if len(arr):
                out[k] = {"p50_ms": round(float(np.percentile(arr, 50)), 3),
                          "p95_ms": round(float(np.percentile(arr, 95)), 3),
                          "max_ms": round(float(arr.max()), 3), "n": int(len(arr))}
        return out


class DualSessionProcessor:
    def __init__(self, session_id: int, exercise_type: str, hello, *,
                 baseline_rom: dict[str, float] | None = None,
                 provenance: str | None = None) -> None:
        s = get_settings()
        self.settings = s
        self.session_id = session_id
        self.exercise_type = exercise_type
        self.hello = hello
        # SIMULATED / PHYSICAL_REGISTERED / UNVERIFIED, decided at the handshake
        # by sensing_service.resolve_provenance (never from the data).
        self.provenance = provenance or (prov.SIMULATED if hello.simulated else prov.PHYSICAL_UNVERIFIED)
        self.layout = ChannelLayout.from_hello(hello)
        self.rate = float(hello.sample_rate_hz)
        self.rep_mode = EXERCISE_REP_MODE.get(exercise_type, RepMode.NONE)
        self.bilateral_mode = EXERCISE_BILATERAL_MODE.get(exercise_type, BilateralMode.UNILATERAL)
        self.baseline_rom = baseline_rom or {}

        self.monitor = StreamMonitor(
            declared_rate_hz=self.rate,
            accel_range_g={i.side.value: i.accel_range_g or 4.0 for i in hello.imus}
            | {s: 4.0 for s in ("LEFT", "RIGHT") if s not in {i.side.value for i in hello.imus}},
            gyro_range_dps={i.side.value: i.gyro_range_dps or 500.0 for i in hello.imus}
            | {s: 500.0 for s in ("LEFT", "RIGHT") if s not in {i.side.value for i in hello.imus}},
            force_units=tuple(self.layout.force_units),
        )
        self.calibrator = self._new_calibrator()
        self.calibration_sequence = 1
        # Set when the current calibration may no longer hold (device
        # reconnected -- the strap may have moved). Analysis continues but
        # every output says so until the wearer recalibrates.
        self.calibration_stale_reason: str | None = None
        self.tilt = {side: TiltEstimator(self.rate) for side in ("LEFT", "RIGHT")}
        self._axis_buffer: dict[str, list[np.ndarray]] = {"LEFT": [], "RIGHT": []}

        self.bundle_bi, self.bundle_bi_reason = model_store.get("bilateral")
        self.bundle_single, self.bundle_single_reason = model_store.get("single_side")
        window_s = self.bundle_bi.window_s if self.bundle_bi else s.hw_window_s
        self.window = SlidingWindowBuffer(window_s, s.hw_stride_s, self.layout.n_channels + 2)

        # Analysis buffer: session time, calibrated data, tilt L, tilt R.
        self._buf_t: deque = deque()
        self._buf_x: deque = deque()

        self.t0: float | None = None
        self.clock = 0.0
        self.reps: dict[str, list[Rep]] = {"LEFT": [], "RIGHT": []}
        self._last_rep_scan = -1.0
        self._last_frame_emit = -1.0
        self._last_health_emit = -1.0
        self._last_assessment = -1.0
        self._cal_bucket = -1
        self._frame_rows: list = []
        self.windows: list[dict] = []
        self.activity_seconds: dict[str, float] = {}
        self.low_conf_windows = 0
        self.total_windows = 0
        self.asym_windows: list[dict] = []
        self.latency = LatencyStats()
        self.device_status: dict = {}
        self.connected = False
        self.disconnects = 0

        # +1/-1 per side: which direction a repetition moves the tilt trace.
        self._rep_sign: dict[str, float] = {}
        self._chunk: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        self._packet_log: list[list] = []
        self._alert_keys: set = set()
        self._last_arrival: tuple[float, float] | None = None
        self._chunk_index = 0
        self._chunk_started: float | None = None

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    @property
    def session_mode(self) -> str:
        return prov.session_mode_for(self.provenance)

    def _new_calibrator(self) -> DeviceCalibrator:
        s = self.settings
        return DeviceCalibrator(
            self.layout, self.rate, still_seconds=s.hw_calibration_still_s,
            movement_seconds=s.hw_calibration_movement_s, health_seconds=s.hw_calibration_health_s,
        )

    def on_connect(self, hello) -> list[Event]:
        if hello.device_id != self.hello.device_id:
            # A different device mid-session would mix two sensors' offsets.
            raise ValueError("a different device is already attached to this session")
        self.hello = hello
        events = []
        if self.disconnects and self.calibrator.complete and self.calibration_stale_reason is None:
            self.calibration_stale_reason = "device reconnected -- the sensors may have moved; recalibrate"
            events.append(Event("calibration_invalidated", {
                "sequence": self.calibration_sequence, "reason": self.calibration_stale_reason,
            }, broadcast=False, persist="calibration_invalidated"))
        self.connected = True
        return events + [self.connection_event(), self.calibration_event()]

    def start_recalibration(self, reason: str = "recalibration requested") -> list[Event]:
        """Begin a new calibration. The previous one is superseded, not edited."""
        previous = self.calibration_sequence if self.calibrator.complete else None
        self.calibrator = self._new_calibrator()
        self.calibration_sequence += 1
        self.calibration_stale_reason = None
        self._cal_bucket = -1
        self.tilt = {side: TiltEstimator(self.rate) for side in ("LEFT", "RIGHT")}
        self._buf_t.clear()
        self._buf_x.clear()
        self.window = SlidingWindowBuffer(self.window.window_s, self.window.stride_s,
                                          self.layout.n_channels + 2)
        events = []
        if previous is not None:
            events.append(Event("calibration_invalidated", {
                "sequence": previous, "reason": f"superseded: {reason}",
            }, broadcast=False, persist="calibration_invalidated"))
        return events + [self.calibration_event()]

    def on_disconnect(self) -> list[Event]:
        self.connected = False
        self.disconnects += 1
        events = [self.connection_event()]
        events += self._flush_chunk()
        return events

    def connection_event(self) -> Event:
        stream = self.monitor.as_dict()

        def imu_state(side):
            if side not in self.layout.imu_sides:
                return "NOT_DECLARED"
            if not self.connected:
                return "DISCONNECTED"
            if self.monitor.accepted == 0:
                return "WAITING"
            if self.monitor.frozen_flags[side]:
                return "FROZEN"
            if self._recent_available(side) < 0.5:
                return "DISCONNECTED"
            return "CONNECTED"

        return Event("hw_connection", {
            "protocol_version": 2,
            "device_id": self.hello.device_id,
            "firmware_version": self.hello.firmware_version,
            "simulated": self.hello.simulated,
            "provenance": self.provenance,
            "scenario": self.hello.scenario,
            "session_mode": self.session_mode,
            "device_connected": self.connected,
            "imus": {side: {
                "state": imu_state(side),
                "placement": self.layout.imu_placements.get(side),
                "available_ratio": stream[f"{side.lower()}_available_ratio"],
            } for side in ("LEFT", "RIGHT")},
            "force_channels": [
                {"id": fid, "side": self.layout.force_sides[j], "unit": self.layout.force_units[j]}
                for j, fid in enumerate(self.layout.force_ids)
            ],
            "declared_rate_hz": self.rate,
            "measured_rate_hz": stream["measured_rate_hz"],
            "device_status": self.device_status,
            "alerts": self.sensor_alerts(),
        })

    def sensor_alerts(self) -> list[dict]:
        """Explicit unavailability codes. A missing sensor is never filled in.

        LEFT_IMU_UNAVAILABLE / RIGHT_IMU_UNAVAILABLE with a reason:
          NOT_DECLARED        the device did not declare it at the handshake
          NO_READINGS         readings are null / absent (I2C read failing)
          FROZEN              identical readings repeated (hung I2C bus)
          CALIBRATION_FAILED  calibration could not use it
          DEVICE_DISCONNECTED the whole device is offline
        FORCE_CHANNEL_UNAVAILABLE with the channel id, for null force values.
        """
        alerts = []
        for side in ("LEFT", "RIGHT"):
            code = f"{side}_IMU_UNAVAILABLE"
            reason = None
            if side not in self.layout.imu_sides:
                reason = "NOT_DECLARED"
            elif not self.connected:
                reason = "DEVICE_DISCONNECTED"
            elif self.monitor.frozen_flags[side]:
                reason = "FROZEN"
            elif self.monitor.accepted and self._recent_available(side) < 0.5:
                reason = "NO_READINGS"
            elif self.calibrator.complete and not self.calibrator.sides[side].usable:
                reason = "CALIBRATION_FAILED"
            if reason:
                alerts.append({"code": code, "side": side, "reason": reason})
        if self.calibration_stale_reason:
            alerts.append({"code": "CALIBRATION_STALE", "reason": self.calibration_stale_reason})
        if self.calibrator.phase is CalPhase.FAILED:
            alerts.append({"code": "CALIBRATION_FAILED",
                           "reason": self.calibrator.failure_reason or "no usable IMU"})
        if self._buf_t and self.layout.n_force:
            _, x = self._analysis_arrays(2.0)
            for j, fid in enumerate(self.layout.force_ids):
                col = x[:, 12 + j]
                if len(col) and np.isnan(col).mean() > 0.5:
                    alerts.append({"code": "FORCE_CHANNEL_UNAVAILABLE", "channel": fid,
                                   "reason": "NO_READINGS"})
        return alerts

    def on_status(self, status: dict) -> list[Event]:
        self.device_status = {k: v for k, v in status.items() if k != "type" and v is not None}
        return [Event("hw_device_status", dict(self.device_status))]

    def _recent_available(self, side: str, seconds: float = 2.0) -> float:
        if not self._buf_t:
            # Before calibration finishes the analysis buffer is empty; fall
            # back to the long-run ratio.
            return self.monitor.side_available_ratio(side)
        t = np.fromiter(self._buf_t, float)
        sel = t >= t[-1] - seconds
        if not sel.any():
            return 0.0
        x = np.vstack(self._buf_x)[sel]
        sl = self.layout.side_slice(side)
        return float((~np.isnan(x[:, sl]).any(axis=1)).mean())

    # ------------------------------------------------------------------ #
    # ingestion
    # ------------------------------------------------------------------ #

    def process(self, samples, arrival: float | None = None,
                sent_ts: float | None = None) -> list[Event]:
        arrival = time.time() if arrival is None else arrival
        t_start = time.perf_counter()
        ts, seq, data = samples_to_array(samples, self.layout)
        keep = self.monitor.observe(ts, seq, data, arrival)
        ts, seq, data = ts[keep], seq[keep], data[keep]
        # A frozen IMU (hung I2C bus repeating one reading) is treated as
        # missing for analysis. The raw chunk below keeps what was received.
        analysis_data = data.copy()
        for side in ("LEFT", "RIGHT"):
            sl = self.layout.side_slice(side)
            if self.monitor.frozen_flags[side]:
                analysis_data[:, sl] = np.nan
                continue
            # Beyond the declared full scale is a corrupt reading, not motion.
            block = np.abs(analysis_data[:, sl])
            with np.errstate(invalid="ignore"):
                bad = ((block[:, 0:3] > 1.05 * self.monitor.accel_range_g[side]).any(axis=1)
                       | (block[:, 3:6] > 1.05 * self.monitor.gyro_range_dps[side]).any(axis=1))
            analysis_data[bad, sl] = np.nan
        events: list[Event] = []
        if len(ts) == 0:
            return events
        first_sample = self.t0 is None
        if first_sample:
            self.t0 = float(ts[0])
        t = ts - self.t0
        if first_sample:
            events.append(self._marker("recording_start", 0.0, "first sample received"))
        self.clock = float(t[-1])

        self._packet_log.append([int(seq[0]), int(len(seq)), round(float(arrival), 6),
                                 None if sent_ts is None else float(sent_ts)])
        self._last_arrival = (float(t[-1]), float(arrival))
        events += self._accumulate_chunk(t, seq, data)
        data = analysis_data

        if not self.calibrator.complete:
            if self.calibrator.phase is CalPhase.PENDING:
                events.append(self._marker("calibration_start", float(t[0]),
                                           f"calibration #{self.calibration_sequence}"))
            self.calibrator.frozen_sides = dict(self.monitor.frozen_flags)
            self.calibrator.observe(t, data, self.monitor.measured_rate_hz)
            bucket = int(self.calibrator.progress * 10)
            if bucket != self._cal_bucket or self.calibrator.complete:
                self._cal_bucket = bucket
                events.append(self.calibration_event())
            if not self.calibrator.complete:
                self.latency.add("preprocessing", (time.perf_counter() - t_start) * 1000)
                events += self._maybe_health()
                return events
            events += self._on_calibrated()
            # Samples in this packet after the calibration window ends are
            # the first analysable ones; do not drop them.
            mv = self.calibrator.windows.get("movement")
            cal_end = mv[1] if mv else float(t[-1])
            after = t > cal_end
            t, seq, data = t[after], seq[after], data[after]
            if len(t) == 0:
                events += self._maybe_health()
                return events

        cal = self.calibrator.apply(data)
        tilt_l, tilt_r = self._update_tilt(t, cal)
        rows = np.column_stack([cal, tilt_l, tilt_r])
        for ti, row in zip(t, rows):
            self._buf_t.append(float(ti))
            self._buf_x.append(row)
        while self._buf_t and self._buf_t[0] < self.clock - ANALYSIS_SECONDS:
            self._buf_t.popleft()
            self._buf_x.popleft()
        self.window.extend(t, rows)
        self.latency.add("preprocessing", (time.perf_counter() - t_start) * 1000)

        events += self._maybe_frame(t, cal, tilt_l, tilt_r)
        for w_start, w_end, w_ts, w_rows in self.window.pop_windows():
            events += self._analyse_window(w_start, w_end, w_ts, w_rows)
        events += self._maybe_reps()
        events += self._maybe_health()
        self.latency.add("process_packet_total", (time.perf_counter() - t_start) * 1000)
        return events

    # ------------------------------------------------------------------ #

    def _accumulate_chunk(self, t, seq, data) -> list[Event]:
        if not self.settings.store_raw_samples:
            return []
        if self._chunk_started is None:
            self._chunk_started = float(t[0])
        self._chunk.append((t.copy(), seq.copy(), data.copy()))
        if float(t[-1]) - self._chunk_started >= 1.0:
            return self._flush_chunk()
        return []

    def _flush_chunk(self) -> list[Event]:
        if not self._chunk:
            return []
        t = np.concatenate([c[0] for c in self._chunk])
        seq = np.concatenate([c[1] for c in self._chunk])
        data = np.vstack([c[2] for c in self._chunk])
        self._chunk, self._chunk_started = [], None
        # Lossless with respect to what the device sent: time float64, seq
        # int64, sensor values float32 (the device sends <= 5 decimals of a
        # 16-bit reading). Missing readings stay NaN; nothing is filled in.
        values = data.astype("<f4")
        payload = {
            "chunk_index": self._chunk_index,
            "t_start": float(t[0]),
            "t_end": float(t[-1]),
            "n_samples": int(len(t)),
            "encoding": RAW_ENCODING,
            "columns": ["t", "seq"] + self.layout.names,
            "data": zlib.compress(t.astype("<f8").tobytes() + seq.astype("<i8").tobytes()
                                  + values.tobytes(), 6),
            "device_t0": self.t0,
            "firmware_version": self.hello.firmware_version,
            "packet_log": self._packet_log,
            "simulated": self.hello.simulated,
        }
        self._packet_log = []
        self._chunk_index += 1
        return [Event("raw_chunk", payload, broadcast=False, persist="raw_chunk")]

    def calibration_event(self) -> Event:
        c = self.calibrator
        payload = {
            "sequence": self.calibration_sequence,
            "phase": c.phase.value,
            "step": {"PENDING": 1, "HEALTH_CHECK": 2, "STILL": 3, "MOVEMENT": 4,
                     "COMPLETE": 7, "FAILED": 7}[c.phase.value],
            "progress": round(c.progress, 3),
            "instruction": {
                "PENDING": "Waiting for sensor data.",
                "HEALTH_CHECK": "Checking both sensors...",
                "STILL": "Stand still with both sensors in the neutral position.",
                "MOVEMENT": "Perform a few slow repetitions of the exercise.",
                "COMPLETE": "Calibration complete.",
                "FAILED": "Calibration failed -- check the sensors and recalibrate.",
            }[c.phase.value],
            "health": c.health,
            "health_attempts": c.health_attempts,
            "complete": c.complete,
            "stale_reason": self.calibration_stale_reason,
        }
        if c.complete:
            payload.update({"status": c.status.value, "quality": c.quality,
                            "failure_reason": c.failure_reason, "windows": c.windows,
                            "checks": [ch.as_dict() for ch in c.checks]})
        return Event("hw_calibration", payload)

    def _marker(self, kind: str, t_session: float, note: str | None = None,
                source: str = "SERVER", label: str | None = None) -> Event:
        """A server-generated marker stamped on the DEVICE_TIME axis.

        Server markers derived from samples (first sample, calibration
        windows, sensor-state changes) use the device time of the sample
        that triggered them, so they share the samples' clock exactly.
        """
        return Event("marker", {"kind": kind, "label": label or kind, "note": note,
                                "source": source, "time_basis": "DEVICE_TIME",
                                "t_session": round(float(t_session), 6), "t_uncertainty_s": 0.0},
                     broadcast=False, persist="marker")

    def _alert_markers(self) -> list[Event]:
        now = {(a["code"], a.get("side") or a.get("channel")): a for a in self.sensor_alerts()}
        events = []
        for key in now.keys() - self._alert_keys:
            a = now[key]
            events.append(self._marker("sensor_failure", self.clock, a["reason"], label=a["code"]))
        for key in self._alert_keys - now.keys():
            events.append(self._marker("sensor_recovered", self.clock, None, label=key[0]))
        self._alert_keys = set(now)
        return events

    def _on_calibrated(self) -> list[Event]:
        for side in ("LEFT", "RIGHT"):
            sc = self.calibrator.sides[side]
            if sc.usable:
                self.tilt[side].configure(sc.g0, sc.axis)
        mv = self.calibrator.windows.get("movement")
        done = self._marker("calibration_complete", mv[1] if mv else self.clock,
                            f"calibration #{self.calibration_sequence}: {self.calibrator.status.value}")
        return [
            done,
            Event("calibration_result", {
                "sequence": self.calibration_sequence,
                "device_id": self.hello.device_id,
                "firmware_version": self.hello.firmware_version,
                "simulated": self.hello.simulated,
                "metadata": self.calibrator.metadata(),
            }, broadcast=False, persist="calibration"),
            self.connection_event(),
        ]

    def _update_tilt(self, t: np.ndarray, cal: np.ndarray):
        out = {"LEFT": np.full(len(t), np.nan), "RIGHT": np.full(len(t), np.nan)}
        for side in ("LEFT", "RIGHT"):
            if not self.calibrator.sides[side].usable:
                continue
            sl = self.layout.side_slice(side)
            est = self.tilt[side]
            block = cal[:, sl]
            if est.axis is None:
                # No calibration movement: learn the axis once the side moves.
                self._axis_buffer[side].append(block[:, 3:6])
                gy = np.vstack(self._axis_buffer[side])
                if len(gy) >= int(3 * self.rate):
                    axis = principal_axis(gy)
                    if axis is not None:
                        est.configure(None, axis)
                        self._axis_buffer[side] = []
                    else:
                        self._axis_buffer[side] = [gy[-int(3 * self.rate):]]
                continue
            prev = self._buf_t[-1] if self._buf_t else None
            for i in range(len(t)):
                dt = (t[i] - prev) if prev is not None else 1.0 / self.rate
                prev = t[i]
                v = est.update(block[i, 0:3], block[i, 3:6], dt)
                out[side][i] = np.nan if v is None else v
        return out["LEFT"], out["RIGHT"]

    def _maybe_frame(self, t, cal, tilt_l, tilt_r) -> list[Event]:
        step = max(1, int(round(self.rate / self.settings.hw_sensor_frame_hz)))
        for i in range(0, len(t), step):
            row = cal[i]
            frame = [round(float(t[i]), 3)]
            for side, tilt in (("LEFT", tilt_l), ("RIGHT", tilt_r)):
                sl = self.layout.side_slice(side)
                v = row[sl]
                if np.isnan(v).any():
                    frame += [None, None, None]
                else:
                    frame += [round(float(np.linalg.norm(v[0:3])), 4),
                              round(float(np.linalg.norm(v[3:6])), 2),
                              None if np.isnan(tilt[i]) else round(float(tilt[i]), 2)]
            frame += [None if np.isnan(row[12 + j]) else round(float(row[12 + j]), 4)
                      for j in range(self.layout.n_force)]
            self._frame_rows.append(frame)
        if self.clock - self._last_frame_emit < 0.2:
            return []
        self._last_frame_emit = self.clock
        rows, self._frame_rows = self._frame_rows, []
        return [Event("hw_sensor_frame", {
            "columns": ["t", "left_acc_g", "left_gyro_dps", "left_tilt_deg",
                        "right_acc_g", "right_gyro_dps", "right_tilt_deg"]
                       + self.layout.names[12:],
            "rows": rows,
            "units": {"acc": "g (|a|, calibrated)", "gyro": "deg/s (|w|, bias-corrected)",
                      "tilt": "deg from neutral (segment tilt, not a joint angle)",
                      "force": list(self.layout.force_units)},
        })]

    def _analysis_arrays(self, seconds: float):
        if not self._buf_t:
            return np.empty(0), np.empty((0, self.layout.n_channels + 2))
        t = np.fromiter(self._buf_t, float)
        x = np.vstack(self._buf_x)
        sel = t >= t[-1] - seconds
        return t[sel], x[sel]

    def _analyse_window(self, w_start, w_end, w_ts, w_rows) -> list[Event]:
        t_inf = time.perf_counter()
        available = {
            side: (side in self.layout.imu_sides and self.calibrator.sides[side].usable
                   and float((~np.isnan(w_rows[:, self.layout.side_slice(side)]).any(axis=1)).mean()) >= 0.9)
            for side in ("LEFT", "RIGHT")
        }
        both = available["LEFT"] and available["RIGHT"]
        bundle = self.bundle_bi if both else self.bundle_single
        neutral = {side: self.calibrator.sides[side].g0 for side in ("LEFT", "RIGHT")}
        activity = classify_window(bundle, w_ts, w_rows[:, :self.layout.n_channels], available,
                                   self.layout.imu_placements, neutral)
        if bundle is None:
            activity["reason"] = self.bundle_bi_reason if both else self.bundle_single_reason
        self.latency.add("inference", (time.perf_counter() - t_inf) * 1000)

        t_feat = time.perf_counter()
        grid_rate = 50.0
        grid = resample_uniform(w_ts, w_rows, grid_rate, t_start=w_start + 1 / grid_rate,
                                n=int(round((w_end - w_start) * grid_rate)))
        n = self.layout.n_channels
        avail_ratio = {side: float(available[side]) for side in ("LEFT", "RIGHT")}
        asym = window_asymmetry(grid[:, 0:6], grid[:, 6:12], grid[:, n], grid[:, n + 1],
                                grid_rate, self.bilateral_mode, avail_ratio)
        if asym.get("asymmetry_score") is not None:
            self.asym_windows.append(asym)

        force = None
        if self.layout.n_force:
            motion = np.nanmean(np.column_stack([
                np.linalg.norm(grid[:, 3:6], axis=1), np.linalg.norm(grid[:, 9:12], axis=1)
            ]), axis=1)
            force = window_force_motion(grid[:, 12:n], motion, grid_rate,
                                        list(self.layout.force_units), list(self.layout.force_ids))

        phases = {}
        for side, col in (("LEFT", n), ("RIGHT", n + 1)):
            reps = self.reps[side]
            if reps and available[side]:
                recent = reps[-3:]
                amp = float(np.mean([r.amplitude_deg for r in recent]))
                tilt = grid[:, col]
                tilt = tilt[np.isfinite(tilt)]
                rest = self._rest_level(side)
                if len(tilt) >= 3 and rest is not None:
                    sign = self._rep_sign.get(side, 1.0)
                    phases[side] = current_phase(sign * tilt, amp, sign * rest)
        self.latency.add("window_analytics", (time.perf_counter() - t_feat) * 1000)

        self.total_windows += 1
        stride = self.window.stride_s
        if activity["status"] == "OK":
            self.activity_seconds[activity["activity"]] = (
                self.activity_seconds.get(activity["activity"], 0.0) + stride
            )
        elif activity["status"] == "LOW_CONFIDENCE":
            self.low_conf_windows += 1

        calibration_required = self.calibrator.phase is CalPhase.FAILED
        payload = {
            "t_start": round(w_start, 3),
            "t_end": round(w_end, 3),
            "activity": activity,
            "phase": {"method": f"heuristic ({DETECTOR_VERSION}); not a trained model",
                      "by_side": phases},
            "bilateral": asym,
            "force_motion": force,
            "imu_available": available,
            "alerts": self.sensor_alerts(),
            "calibration_required": calibration_required,
            "calibration": {"sequence": self.calibration_sequence,
                            "status": self.calibrator.status.value,
                            "valid": self.calibration_stale_reason is None and not calibration_required,
                            "stale_reason": self.calibration_stale_reason},
            # Over the whole session so far (>= 3 repetitions), not this window.
            "movement_quality": self._running_mqi(),
        }
        events = [Event("hw_ml_update", payload)]
        events.append(Event("activity_result", {
            "t_start": w_start, "t_end": w_end, **{k: activity.get(k) for k in (
                "status", "activity", "candidate", "confidence", "probabilities", "model",
                "inference_ms")},
        }, broadcast=False, persist="activity"))
        if self.clock - self._last_assessment >= self.settings.hw_assessment_interval_s:
            self._last_assessment = self.clock
            events.append(Event("movement_assessment", {
                "kind": "WINDOW", "t_start": w_start, "t_end": w_end,
                "bilateral": asym, "force_motion": force,
                "phase": payload["phase"], "mqi": payload["movement_quality"],
            }, broadcast=False, persist="assessment"))
        return events

    def _rest_level(self, side: str) -> float | None:
        reps = self.reps[side]
        if not reps:
            return None
        t, x = self._analysis_arrays(ANALYSIS_SECONDS)
        col = self.layout.n_channels + (0 if side == "LEFT" else 1)
        starts = [r.t_start for r in reps[-3:]]
        vals = [x[np.argmin(np.abs(t - s)), col] for s in starts if len(t)]
        vals = [v for v in vals if np.isfinite(v)]
        return float(np.mean(vals)) if vals else None

    def _maybe_reps(self) -> list[Event]:
        if self.rep_mode is RepMode.NONE or self.clock - self._last_rep_scan < 1.0:
            return []
        self._last_rep_scan = self.clock
        t_rep = time.perf_counter()
        t, x = self._analysis_arrays(REP_SCAN_SECONDS)
        if len(t) < self.rate * 2:
            return []
        events = []
        n = self.layout.n_channels
        for side, col in (("LEFT", n), ("RIGHT", n + 1)):
            if not self.calibrator.sides[side].usable:
                continue
            tilt = x[:, col]
            ok = np.isfinite(tilt)
            # After a dropout, use the latest contiguous valid stretch rather
            # than waiting for the gap to scroll out of the scan window.
            bad = np.flatnonzero(~ok)
            if len(bad):
                ok = np.zeros_like(ok)
                ok[bad[-1] + 1:] = True
            if ok.sum() < self.rate * 2:
                continue
            sl = self.layout.side_slice(side)
            axis = self.tilt[side].axis
            if axis is None:
                continue
            w_axis = np.einsum("ij,j->i", np.nan_to_num(x[:, sl][:, 3:6]), axis)
            # Resample to 50 Hz for detection: cheaper peak search, same reps.
            grid_rate = 50.0
            grid = resample_uniform(t[ok], np.column_stack([tilt[ok], w_axis[ok]]), grid_rate)
            gt = t[ok][0] + np.arange(len(grid)) / grid_rate
            force = None
            side_force = self.layout.force_channels_for(side) or (
                self.layout.force_channels_for(None) if self.layout.n_force else []
            )
            if side_force:
                f = x[:, 12 + side_force[0]]
                fok = np.isfinite(f) & ok
                if fok.sum() > 4:
                    force = np.interp(gt, t[fok], f[fok])
            found = detect_reps(side, gt, grid[:, 0], grid[:, 1], grid_rate, self.rep_mode,
                                force=force, start_index=len(self.reps[side]))
            self._rep_sign[side] = movement_sign(grid[:, 0])
            last_end = self.reps[side][-1].t_end if self.reps[side] else -1e9
            for rep in found:
                # Only reps that finished after the last one we reported, and
                # that are not still open at the edge of the buffer.
                if rep.t_peak <= last_end or rep.t_end > self.clock - 0.3:
                    continue
                rep.index = len(self.reps[side]) + 1
                self.reps[side].append(rep)
                last_end = rep.t_end
                payload = rep.as_dict()
                payload["kind"] = "gait_cycle" if self.rep_mode is RepMode.GAIT_CYCLE else "repetition"
                payload["unit_note"] = "rom_proxy_deg is segment tilt range, not a joint angle"
                events.append(Event("hw_rep", payload, persist="rep"))
        self.latency.add("repetition_detection", (time.perf_counter() - t_rep) * 1000)
        return events

    def _stream_quality(self) -> float:
        m = self.monitor
        avail = [m.side_available_ratio(s) for s in self.layout.imu_sides]
        rate_factor = 1.0 if m.rate_ok in (True, None) else 0.7
        return float(max(0.0, min(1.0, (1.0 - m.loss_ratio) * (min(avail) if avail else 0) * rate_factor)))

    def _bilateral_summary(self) -> dict:
        both_declared = {"LEFT", "RIGHT"} <= set(self.layout.imu_sides)
        both_usable = all(self.calibrator.sides[s].usable for s in ("LEFT", "RIGHT"))
        if not both_declared or (self.calibrator.complete and not both_usable):
            return {"version": BILATERAL_VERSION, "status": "SINGLE_SIDE",
                    "asymmetry_score": None, "confidence": 0.0,
                    "message": "Only one usable IMU; a bilateral comparison needs both.",
                    "mode": self.bilateral_mode.value}
        if self.bilateral_mode is BilateralMode.UNILATERAL and self.rep_mode is not RepMode.NONE:
            return rep_asymmetry(self.reps["LEFT"], self.reps["RIGHT"])
        wins = [w for w in self.asym_windows if w.get("asymmetry_score") is not None]
        if len(wins) < 4:
            return {"version": BILATERAL_VERSION, "status": "INSUFFICIENT_DATA",
                    "asymmetry_score": None, "confidence": 0.0,
                    "message": "Not enough two-sided movement windows yet.",
                    "mode": self.bilateral_mode.value}
        w = np.asarray([x["confidence"] for x in wins])
        s = np.asarray([x["asymmetry_score"] for x in wins])
        comps = {}
        for k in {k for x in wins for k in x["components"]}:
            vals = [x["components"][k] for x in wins if x["components"].get(k) is not None]
            if vals:
                comps[k] = round(float(np.median(vals)), 4)
        score = float(np.average(s, weights=np.maximum(w, 1e-6)))
        return {
            "version": BILATERAL_VERSION, "status": "OK", "mode": self.bilateral_mode.value,
            "label": wins[-1]["label"], "asymmetry_score": round(score, 4),
            "components": comps, "windows": len(wins),
            "confidence": round(float(min(1.0, np.mean(w) * min(1.0, len(wins) / 20))), 3),
        }

    def _running_mqi(self) -> dict:
        reps = self.reps["LEFT"] + self.reps["RIGHT"]
        base = None
        if self.baseline_rom:
            vals = [v for v in self.baseline_rom.values() if v]
            base = float(np.mean(vals)) if vals else None
        return movement_quality(reps, self._bilateral_summary(), base,
                                self._stream_quality(), self.calibrator.quality)

    def _maybe_health(self) -> list[Event]:
        if self.clock - self._last_health_emit < 2.0:
            return []
        self._last_health_emit = self.clock
        return self._alert_markers() + [Event("hw_stream_health", {
            **self.monitor.as_dict(),
            "stream_quality": round(self._stream_quality(), 3),
            "latency": self.latency.as_dict(),
        }), self.connection_event()]

    # ------------------------------------------------------------------ #
    # finalisation
    # ------------------------------------------------------------------ #

    def flush(self) -> list[Event]:
        events = self._flush_chunk()
        if self.t0 is not None:
            # Final sensor-state evaluation, so a change in the last second
            # before the stop is still marked.
            events += self._alert_markers()
            events.append(self._marker("recording_stop", self.clock, "session ended"))
        return events

    def device_event(self, ev) -> list[Event]:
        """An event the device stamped on its own clock."""
        if self.t0 is None:
            return []
        return [Event("marker", {"kind": ev.kind if ev.kind in _KINDS else "note",
                                 "label": ev.kind, "note": ev.note, "source": "DEVICE",
                                 "time_basis": "DEVICE_TIME",
                                 "t_session": round(ev.ts - self.t0, 6), "t_uncertainty_s": 0.0},
                      broadcast=False, persist="marker")]

    def map_server_time(self, server_now: float) -> tuple[float | None, float | None]:
        """Map a server wall-clock instant (a user click) onto DEVICE_TIME.

        t_device ~ last received sample time + (now - its arrival). The
        uncertainty is the observed packet arrival delay (p95) plus one packet
        interval, because the click and the samples took different paths.
        """
        if self.t0 is None or not self._last_arrival:
            return None, None
        t_last, arrival = self._last_arrival
        est = t_last + max(0.0, server_now - arrival)
        delays = self.monitor.clock()["packet_arrival_delay_ms"]
        unc = ((delays.get("p95") or 0.0) / 1000.0) + 0.1
        return round(est, 6), round(unc, 4)

    def finalize(self) -> dict:
        if not self.calibrator.complete:
            self.calibrator.force_finalise(self.monitor.measured_rate_hz)
        self._last_rep_scan = -1.0
        self.clock += 0.31  # let the final rep close
        self._maybe_reps()
        self.clock -= 0.31

        bilateral = self._bilateral_summary()
        mqi = self._running_mqi()
        rep_summary = {}
        for side, reps in self.reps.items():
            if not reps:
                continue
            sp = [r.smoothness_sparc for r in reps if r.smoothness_sparc is not None]
            rep_summary[side] = {
                "count": len(reps),
                "rom_proxy_deg_mean": round(float(np.mean([r.amplitude_deg for r in reps])), 2),
                "peak_velocity_dps_mean": round(float(np.mean([r.peak_velocity_dps for r in reps])), 1),
                "duration_s_mean": round(float(np.mean([r.duration_s for r in reps])), 3),
                "sparc_median": None if not sp else round(float(np.median(sp)), 3),
            }
        t, x = self._analysis_arrays(ANALYSIS_SECONDS)
        phase_force = None
        if self.layout.n_force and len(t):
            all_reps = self.reps["LEFT"] + self.reps["RIGHT"]
            phase_force = {fid: force_by_phase(t, x[:, 12 + j], all_reps)
                           for j, fid in enumerate(self.layout.force_ids)}
        force = session_force_motion(self.reps, list(self.layout.force_sides),
                                     list(self.layout.force_ids), list(self.layout.force_units),
                                     phase_force)
        stream = self.monitor.as_dict()
        sq = self._stream_quality()
        conf_value = round(sq * (self.calibrator.quality or 0.0), 3)
        total_reps = sum(len(r) for r in self.reps.values())
        classified = sum(self.activity_seconds.values())
        model = self.bundle_bi or self.bundle_single
        return {
            "analytics_version": PIPELINE_VERSION,
            "pipeline": {
                "pipeline_version": PIPELINE_VERSION,
                "feature_version": FEATURE_VERSION,
                "preprocessing_version": PREPROCESSING_VERSION,
                "calibration_version": self.calibrator.metadata()["calibration_version"],
                "detector_version": DETECTOR_VERSION,
                "bilateral_version": BILATERAL_VERSION,
                "mqi_version": MQI_VERSION,
            },
            "protocol_version": 2,
            "duration_s": round(self.clock, 2),
            "exercise_type": self.exercise_type,
            "session_mode": self.session_mode,
            "sensor_alerts_at_end": self.sensor_alerts(),
            "device": {"device_id": self.hello.device_id,
                       "firmware_version": self.hello.firmware_version,
                       "simulated": self.hello.simulated,
                       "layout": self.layout.as_dict(),
                       "disconnects": self.disconnects},
            "repetitions": total_reps,
            "repetition_summary": rep_summary,
            "repetition_kind": self.rep_mode.value,
            "activity": {
                "model": None if model is None else f"{model.name}/{model.version}",
                "seconds_by_activity": {k: round(v, 1) for k, v in self.activity_seconds.items()},
                "classified_seconds": round(classified, 1),
                "windows": self.total_windows,
                "low_confidence_windows": self.low_conf_windows,
                "unavailable_reason": None if model else self.bundle_bi_reason,
            },
            "bilateral": bilateral,
            "force_motion": force,
            "movement_quality": mqi,
            "calibration": self.calibrator.metadata() | {
                "sequence": self.calibration_sequence,
                "stale_reason": self.calibration_stale_reason},
            "stream": stream,
            "latency": self.latency.as_dict(),
            "confidence": {
                "value": conf_value,
                "percent": round(conf_value * 100),
                "band": "Higher" if conf_value >= 0.75 else "Moderate" if conf_value >= 0.5 else "Lower",
                "coverage": round(1.0 - self.monitor.loss_ratio, 3),
                "bilateral_coverage": round(min(stream["left_available_ratio"],
                                                stream["right_available_ratio"]), 3),
                "signal_quality": round(sq, 3),
                "explanation": "Stream completeness x calibration quality for this session.",
            },
            "data_quality": {"stream": stream, "calibration_status": self.calibrator.status.value},
            # Fields v1 surfaces read. Not computable from one IMU per leg, so
            # explicitly null rather than approximated.
            "rom_deg": None,
            "symmetry_index_pct": None,
            "recovery_score": None,
            "validation": {
                "public_dataset": "See the model bundle's metrics (public-dataset evaluation only).",
                "rehabsense_hardware": "NOT_VALIDATED",
                "clinical": "NOT_VALIDATED",
            },
            "disclaimer": (
                "Research prototype. Activity, asymmetry, force/motion and MQI values are "
                "engineering indicators from a public-dataset-pretrained model and signal "
                "processing; none are clinically validated or diagnostic."
            ),
        }
