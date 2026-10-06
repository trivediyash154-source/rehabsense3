"""Device calibration for the dual-IMU + force device.

Run every time the device is put on, because strapping it on again changes
each IMU's orientation. Two timed phases:

    STILL     (default 3 s)  the wearer stands/sits still in a neutral pose
    MOVEMENT  (default 5 s)  a few slow repetitions of the session's movement

and eight checks, in the order the specification lists them:

    1 imu_connectivity     each declared IMU delivers non-frozen readings
    2 sampling_rate        measured rate from device timestamps vs declared
    3 orientation          neutral gravity direction per IMU, |g| plausibility
    4 accel_baseline       accelerometer offset / stillness during STILL
    5 gyro_baseline        gyroscope bias and noise during STILL
    6 force_sensor         presence, offset, noise, saturation, load response
    7 neutral_position     the stored neutral pose (gravity vector per IMU)
    8 baseline_movement    rotation axis and movement amplitude per IMU

No MPU6050 is assumed to match another: offsets, bias and orientation are
estimated per sensor, per wearing. The thresholds below are engineering
choices for MPU6050-class sensors and are exported with the result so a
stored calibration is always interpretable.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field

import numpy as np

from app.sensing.channels import ChannelLayout
from app.sensing.orientation import TiltEstimator, principal_axis, unit

THRESHOLDS = {
    "available_ratio_min": 0.95,
    "gravity_norm_pass": (0.90, 1.10),
    "gravity_norm_warn": (0.80, 1.20),
    "accel_still_std_pass_g": 0.02,
    "accel_still_std_warn_g": 0.05,
    "gyro_noise_pass_dps": 1.0,
    "gyro_noise_warn_dps": 3.0,
    "gyro_bias_warn_dps": 20.0,
    "rate_pass": 0.05,
    "rate_warn": 0.15,
    "force_saturation": 0.98,
    "movement_rms_min_dps": 6.0,
    # Health check: a declared IMU must deliver plausible, changing readings.
    "health_available_min": 0.9,
    "health_gravity_range_g": (0.5, 1.5),
    # Stillness detector for the neutral pose (before bias removal; bias does
    # not change a standard deviation).
    "still_accel_std_max_g": 0.03,
    "still_gyro_std_max_dps": 2.5,
    "still_timeout_s": 20.0,
}
CALIBRATION_VERSION = "dual-cal-v2"


class CalPhase(str, enum.Enum):
    PENDING = "PENDING"
    HEALTH_CHECK = "HEALTH_CHECK"
    STILL = "STILL"
    MOVEMENT = "MOVEMENT"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class CheckStatus(str, enum.Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


@dataclass
class Check:
    key: str
    status: CheckStatus
    message: str
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"key": self.key, "status": self.status.value, "message": self.message,
                "detail": self.detail}


@dataclass
class SideCalibration:
    usable: bool = False
    gyro_bias: np.ndarray = field(default_factory=lambda: np.zeros(3))
    accel_scale: float = 1.0
    g0: np.ndarray | None = None
    axis: np.ndarray | None = None

    def apply(self, block: np.ndarray) -> np.ndarray:
        out = block.copy()
        out[:, 0:3] = block[:, 0:3] * self.accel_scale
        out[:, 3:6] = block[:, 3:6] - self.gyro_bias
        return out

    def as_dict(self) -> dict:
        def vec(v):
            return None if v is None else [round(float(x), 5) for x in v]
        return {
            "usable": self.usable,
            "gyro_bias_dps": vec(self.gyro_bias),
            "accel_scale": round(float(self.accel_scale), 5),
            "neutral_gravity_unit": vec(self.g0),
            "rotation_axis_unit": vec(self.axis),
        }


def _worst(statuses: list[CheckStatus]) -> CheckStatus:
    for s in (CheckStatus.FAIL, CheckStatus.WARN, CheckStatus.PASS):
        if s in statuses:
            return s
    return CheckStatus.SKIPPED


@dataclass
class DeviceCalibrator:
    """The calibration workflow, one instance per calibration attempt.

        HEALTH_CHECK  health_seconds of data: each declared IMU must deliver
                      readings that are present, changing (not frozen) and
                      gravity-plausible. No healthy IMU -> retry, never proceed.
        STILL         wait until the last still_seconds are genuinely still
                      on every healthy IMU (detected, not assumed from a
                      timer); give up after still_timeout_s -> FAILED.
        MOVEMENT      movement_seconds of slow repetitions.
        COMPLETE / FAILED

    The exact sample windows used are recorded (`windows`), so the result
    can be recomputed from stored raw data: see `recompute()`.
    """

    layout: ChannelLayout
    declared_rate_hz: float
    still_seconds: float = 3.0
    movement_seconds: float = 5.0
    health_seconds: float = 1.0

    phase: CalPhase = CalPhase.PENDING
    checks: list[Check] = field(default_factory=list)
    sides: dict[str, SideCalibration] = field(
        default_factory=lambda: {"LEFT": SideCalibration(), "RIGHT": SideCalibration()}
    )
    force_offset: list[float | None] = field(default_factory=list)
    force_noise: list[float | None] = field(default_factory=list)
    quality: float | None = None
    measured_rate_hz: float | None = None
    health: dict = field(default_factory=dict)
    health_attempts: int = 0
    failure_reason: str | None = None
    windows: dict = field(default_factory=dict)
    # Set by the processor from the stream monitor: a frozen IMU is masked to
    # NaN before it reaches here, and must still be reported as FROZEN.
    frozen_sides: dict = field(default_factory=dict)

    _phase_t0: float | None = field(default=None, init=False)
    _buf_t: list[np.ndarray] = field(default_factory=list, init=False)
    _buf_x: list[np.ndarray] = field(default_factory=list, init=False)
    _still_block: np.ndarray | None = field(default=None, init=False)
    _still_ts: np.ndarray | None = field(default=None, init=False)
    _elapsed: float = field(default=0.0, init=False)
    _still_progress: float = field(default=0.0, init=False)

    @property
    def complete(self) -> bool:
        return self.phase in (CalPhase.COMPLETE, CalPhase.FAILED)

    @property
    def progress(self) -> float:
        if self.complete:
            return 1.0
        if self.phase in (CalPhase.PENDING, CalPhase.HEALTH_CHECK):
            return 0.1 * min(1.0, self._elapsed / max(self.health_seconds, 1e-6))
        if self.phase is CalPhase.STILL:
            return 0.1 + 0.4 * self._still_progress
        return 0.5 + 0.5 * min(1.0, self._elapsed / max(self.movement_seconds, 1e-6))

    def _buffered(self) -> tuple[np.ndarray, np.ndarray]:
        if not self._buf_t:
            return np.empty(0), np.empty((0, self.layout.n_channels))
        return np.concatenate(self._buf_t), np.vstack(self._buf_x)

    def _enter(self, phase: CalPhase, t: float) -> None:
        self.phase = phase
        self._phase_t0 = t
        self._elapsed = 0.0
        self._buf_t, self._buf_x = [], []

    def observe(self, ts: np.ndarray, data: np.ndarray, rate_hz: float | None) -> None:
        """Feed accepted samples (session-time ts, raw data).

        A large block (a packet may hold up to 500 samples) is processed in
        small steps, so phase transitions land on the right sample whatever
        the packet size.
        """
        step = max(1, int(self.declared_rate_hz / 10))
        for i in range(0, len(ts), step):
            if self.complete:
                return
            self._observe(ts[i:i + step], data[i:i + step], rate_hz)

    def _observe(self, ts: np.ndarray, data: np.ndarray, rate_hz: float | None) -> None:
        if self.complete or len(ts) == 0:
            return
        if self.phase is CalPhase.PENDING:
            self._enter(CalPhase.HEALTH_CHECK, float(ts[0]))
        self.measured_rate_hz = rate_hz
        self._buf_t.append(ts)
        self._buf_x.append(data)
        self._elapsed = float(ts[-1]) - self._phase_t0
        if self.phase is CalPhase.HEALTH_CHECK and self._elapsed >= self.health_seconds:
            self._health_check(float(ts[-1]))
        elif self.phase is CalPhase.STILL:
            self._detect_still(float(ts[-1]))
        elif self.phase is CalPhase.MOVEMENT and self._elapsed >= self.movement_seconds:
            t, x = self._buffered()
            self.windows["movement"] = [round(float(t[0]), 4), round(float(t[-1]), 4)]
            self._finalise(self._still_block, x, t)

    # -- step 2: sensor health ------------------------------------------- #
    def _health_check(self, now: float) -> None:
        _, x = self._buffered()
        lo, hi = THRESHOLDS["health_gravity_range_g"]
        self.health = {}
        for side in ("LEFT", "RIGHT"):
            if side not in self.layout.imu_sides:
                self.health[side] = {"ok": False, "reason": "NOT_DECLARED"}
                continue
            block = x[:, self.layout.side_slice(side)]
            ok_rows = ~np.isnan(block).any(axis=1)
            ratio = float(ok_rows.mean()) if len(block) else 0.0
            good = block[ok_rows]
            if self.frozen_sides.get(side):
                self.health[side] = {"ok": False, "reason": "FROZEN"}
            elif ratio < THRESHOLDS["health_available_min"]:
                self.health[side] = {"ok": False, "reason": "NO_READINGS", "available": round(ratio, 3)}
            elif len(good) > 1 and np.all(np.ptp(good, axis=0) == 0):
                self.health[side] = {"ok": False, "reason": "FROZEN"}
            else:
                g = float(np.median(np.linalg.norm(good[:, 0:3], axis=1)))
                if not lo <= g <= hi:
                    self.health[side] = {"ok": False, "reason": "IMPLAUSIBLE_GRAVITY",
                                         "gravity_norm_g": round(g, 3)}
                else:
                    self.health[side] = {"ok": True, "available": round(ratio, 3),
                                         "gravity_norm_g": round(g, 3)}
        self.health_attempts += 1
        if any(h["ok"] for h in self.health.values()):
            self._enter(CalPhase.STILL, now)
        else:
            # Nothing usable: report and try again -- never calibrate garbage.
            self._enter(CalPhase.HEALTH_CHECK, now)

    # -- step 3/4: neutral pose, detected ------------------------------- #
    def _detect_still(self, now: float) -> None:
        t, x = self._buffered()
        if len(t) < 2:
            return
        win = t >= t[-1] - self.still_seconds
        span = float(t[win][-1] - t[win][0]) if win.any() else 0.0
        healthy = [s for s, h in self.health.items() if h.get("ok")]
        still = True
        for side in healthy:
            block = x[win][:, self.layout.side_slice(side)]
            block = block[~np.isnan(block).any(axis=1)]
            if len(block) < 5 or block[:, 0:3].std(axis=0).max() > THRESHOLDS["still_accel_std_max_g"] \
                    or block[:, 3:6].std(axis=0).max() > THRESHOLDS["still_gyro_std_max_dps"]:
                still = False
                break
        self._still_progress = min(1.0, span / self.still_seconds) if still else 0.0
        if still and span >= self.still_seconds * 0.98:
            self._still_block, self._still_ts = x[win], t[win]
            self.windows["still"] = [round(float(t[win][0]), 4), round(float(t[win][-1]), 4)]
            self._enter(CalPhase.MOVEMENT, now)
            return
        if self._elapsed > THRESHOLDS["still_timeout_s"]:
            self.failure_reason = (f"no still period of {self.still_seconds:.0f} s detected within "
                                   f"{THRESHOLDS['still_timeout_s']:.0f} s")
            self._still_block = x[win]
            self.windows["still"] = None
            self._finalise(np.empty((0, self.layout.n_channels)), np.empty((0, self.layout.n_channels)),
                           np.empty(0))
            self.phase = CalPhase.FAILED
            return
        # Keep only what a still window could still use.
        keep = t >= t[-1] - self.still_seconds * 1.5
        self._buf_t, self._buf_x = [t[keep]], [x[keep]]

    def force_finalise(self, rate_hz: float | None = None) -> None:
        """End early (session ended / device left). Uses whatever was collected."""
        if self.complete:
            return
        self.measured_rate_hz = rate_hz if rate_hz is not None else self.measured_rate_hz
        t, x = self._buffered()
        empty = np.empty((0, self.layout.n_channels))
        if self.phase is CalPhase.MOVEMENT:
            self._finalise(self._still_block, x, t)
        else:
            self.failure_reason = self.failure_reason or f"ended during {self.phase.value}"
            self._finalise(x if self.phase is CalPhase.STILL else empty, empty, np.empty(0))

    # ------------------------------------------------------------------ #

    def _finalise(self, still: np.ndarray | None, move: np.ndarray, move_ts: np.ndarray) -> None:
        still = np.empty((0, self.layout.n_channels)) if still is None else still
        self.checks = []
        min_rows = max(10, int(0.5 * self.declared_rate_hz))

        # 1 connectivity -------------------------------------------------
        conn = {}
        for side in ("LEFT", "RIGHT"):
            sl = self.layout.side_slice(side)
            declared = side in self.layout.imu_sides
            block = still[:, sl]
            if not declared:
                conn[side] = (CheckStatus.SKIPPED, "not declared by the device")
                continue
            if len(block) < min_rows:
                conn[side] = (CheckStatus.FAIL, "too few samples received")
                continue
            ok = ~np.isnan(block).any(axis=1)
            ratio = float(ok.mean())
            frozen = bool(len(block[ok]) > 1 and np.all(np.ptp(block[ok], axis=0) == 0))
            if frozen:
                conn[side] = (CheckStatus.FAIL, "readings are frozen (I2C bus hung?)")
            elif ratio < THRESHOLDS["available_ratio_min"]:
                conn[side] = (CheckStatus.FAIL, f"only {ratio:.0%} of readings arrived")
            else:
                conn[side] = (CheckStatus.PASS, f"{ratio:.1%} of readings arrived")
                self.sides[side].usable = True
        self.checks.append(Check(
            "imu_connectivity", _worst([s for s, _ in conn.values()]),
            "; ".join(f"{k}: {m}" for k, (_, m) in conn.items()),
            {k: s.value for k, (s, _) in conn.items()},
        ))

        # 2 sampling rate ------------------------------------------------
        rate = self.measured_rate_hz
        if rate is None:
            self.checks.append(Check("sampling_rate", CheckStatus.FAIL,
                                     "could not measure the sampling rate", {}))
        else:
            err = abs(rate - self.declared_rate_hz) / self.declared_rate_hz
            status = (CheckStatus.PASS if err <= THRESHOLDS["rate_pass"]
                      else CheckStatus.WARN if err <= THRESHOLDS["rate_warn"] else CheckStatus.FAIL)
            self.checks.append(Check(
                "sampling_rate", status,
                f"measured {rate:.1f} Hz vs declared {self.declared_rate_hz:.1f} Hz ({err:.1%})",
                {"measured_hz": round(rate, 2), "declared_hz": self.declared_rate_hz},
            ))

        # 3 orientation, 4 accel, 5 gyro, 7 neutral -----------------------
        orient, accel, gyro = {}, {}, {}
        for side in ("LEFT", "RIGHT"):
            cal = self.sides[side]
            if not cal.usable:
                continue
            block = still[:, self.layout.side_slice(side)]
            block = block[~np.isnan(block).any(axis=1)]
            acc, gyr = block[:, 0:3], block[:, 3:6]
            mean_acc = acc.mean(axis=0)
            norm = float(np.linalg.norm(mean_acc))
            lo, hi = THRESHOLDS["gravity_norm_pass"]
            wlo, whi = THRESHOLDS["gravity_norm_warn"]
            st = (CheckStatus.PASS if lo <= norm <= hi
                  else CheckStatus.WARN if wlo <= norm <= whi else CheckStatus.FAIL)
            cal.g0 = unit(mean_acc)
            cal.accel_scale = 1.0 / norm if norm > 1e-6 else 1.0
            tilt_from_z = (
                None if cal.g0 is None
                else round(math.degrees(math.acos(max(-1.0, min(1.0, float(cal.g0[2]))))), 1)
            )
            orient[side] = (st, {"gravity_norm_g": round(norm, 4),
                                 "neutral_gravity_unit": [round(float(x), 4) for x in (cal.g0 if cal.g0 is not None else [])],
                                 "angle_from_sensor_z_deg": tilt_from_z})
            if st is CheckStatus.FAIL:
                cal.usable = False

            acc_std = float(np.max(acc.std(axis=0)))
            st = (CheckStatus.PASS if acc_std <= THRESHOLDS["accel_still_std_pass_g"]
                  else CheckStatus.WARN if acc_std <= THRESHOLDS["accel_still_std_warn_g"]
                  else CheckStatus.FAIL)
            accel[side] = (st, {"offset_g": [round(float(x), 4) for x in mean_acc],
                                "max_axis_std_g": round(acc_std, 4)})

            bias = gyr.mean(axis=0)
            noise = float(np.max(gyr.std(axis=0)))
            st = (CheckStatus.PASS if noise <= THRESHOLDS["gyro_noise_pass_dps"]
                  else CheckStatus.WARN if noise <= THRESHOLDS["gyro_noise_warn_dps"]
                  else CheckStatus.FAIL)
            if st is CheckStatus.PASS and float(np.max(np.abs(bias))) > THRESHOLDS["gyro_bias_warn_dps"]:
                st = CheckStatus.WARN
            cal.gyro_bias = bias
            gyro[side] = (st, {"bias_dps": [round(float(x), 3) for x in bias],
                               "max_axis_noise_dps": round(noise, 3)})

        for key, results, label in (
            ("orientation", orient, "gravity magnitude"),
            ("accel_baseline", accel, "stillness"),
            ("gyro_baseline", gyro, "bias/noise"),
        ):
            if not results:
                self.checks.append(Check(key, CheckStatus.SKIPPED, "no usable IMU", {}))
                continue
            self.checks.append(Check(
                key, _worst([s for s, _ in results.values()]),
                "; ".join(f"{k}: {s.value} ({label})" for k, (s, _) in results.items()),
                {k: d for k, (_, d) in results.items()},
            ))

        # 6 force ----------------------------------------------------------
        self.force_offset, self.force_noise = [], []
        force_results = {}
        for j, fid in enumerate(self.layout.force_ids):
            col = 12 + j
            s_col = still[:, col] if len(still) else np.empty(0)
            m_col = move[:, col] if len(move) else np.empty(0)
            s_ok = s_col[~np.isnan(s_col)]
            if len(s_ok) < min_rows:
                force_results[fid] = (CheckStatus.FAIL, {"reason": "no readings"})
                self.force_offset.append(None)
                self.force_noise.append(None)
                continue
            offset, noise = float(np.median(s_ok)), float(s_ok.std())
            self.force_offset.append(offset)
            self.force_noise.append(noise)
            m_ok = m_col[~np.isnan(m_col)]
            detail = {"offset": round(offset, 4), "noise": round(noise, 5),
                      "unit": self.layout.force_units[j]}
            if offset >= THRESHOLDS["force_saturation"]:
                force_results[fid] = (CheckStatus.FAIL, {**detail, "reason": "saturated at rest"})
            elif len(m_ok) and float(m_ok.std()) > max(3 * noise, 0.01):
                force_results[fid] = (CheckStatus.PASS, {**detail, "load_response": True})
            else:
                # An unloaded FSR legitimately reads ~0; only the lack of any
                # response during movement is suspicious.
                force_results[fid] = (CheckStatus.WARN, {**detail, "load_response": False,
                                                         "reason": "no load response observed during movement"})
        if not self.layout.force_ids:
            self.checks.append(Check("force_sensor", CheckStatus.SKIPPED,
                                     "device declared no force channels", {}))
        else:
            self.checks.append(Check(
                "force_sensor", _worst([s for s, _ in force_results.values()]),
                "; ".join(f"{k}: {s.value}" for k, (s, _) in force_results.items()),
                {k: d for k, (_, d) in force_results.items()},
            ))

        neutral = {s: c.as_dict()["neutral_gravity_unit"] for s, c in self.sides.items() if c.usable}
        self.checks.append(Check(
            "neutral_position",
            CheckStatus.PASS if neutral else CheckStatus.FAIL,
            "neutral pose stored" if neutral else "no usable IMU to store a neutral pose",
            neutral,
        ))

        # 8 baseline movement ---------------------------------------------
        moves = {}
        for side in ("LEFT", "RIGHT"):
            cal = self.sides[side]
            if not cal.usable:
                continue
            block = move[:, self.layout.side_slice(side)] if len(move) else np.empty((0, 6))
            ok = ~np.isnan(block).any(axis=1)
            block, ts = block[ok], (move_ts[ok] if len(move_ts) else move_ts)
            if len(block) < min_rows:
                moves[side] = (CheckStatus.WARN, {"reason": "no movement phase recorded"})
                continue
            corrected = cal.apply(block)
            gyr = corrected[:, 3:6]
            rms = float(np.sqrt(np.mean(np.sum(gyr * gyr, axis=1))))
            axis = principal_axis(gyr, THRESHOLDS["movement_rms_min_dps"])
            if axis is None:
                moves[side] = (CheckStatus.WARN, {
                    "gyro_rms_dps": round(rms, 2),
                    "reason": "no clear movement; rotation axis will be learned from the session",
                })
                continue
            cal.axis = axis
            est = TiltEstimator(self.declared_rate_hz)
            est.configure(cal.g0, cal.axis)
            tilts = []
            for i in range(len(corrected)):
                dt = 1.0 / self.declared_rate_hz if i == 0 else float(ts[i] - ts[i - 1])
                v = est.update(corrected[i, 0:3], corrected[i, 3:6], dt)
                if v is not None:
                    tilts.append(v)
            tilt_range = float(np.ptp(tilts)) if tilts else None
            moves[side] = (CheckStatus.PASS, {
                "gyro_rms_dps": round(rms, 2),
                "rotation_axis_unit": [round(float(x), 4) for x in axis],
                "tilt_observable": est.observable,
                "tilt_range_deg": None if tilt_range is None else round(tilt_range, 1),
            })
        self.checks.append(Check(
            "baseline_movement",
            _worst([s for s, _ in moves.values()]) if moves else CheckStatus.FAIL,
            "; ".join(f"{k}: {s.value}" for k, (s, _) in moves.items()) or "no usable IMU",
            {k: d for k, (_, d) in moves.items()},
        ))

        # overall --------------------------------------------------------
        weights = {CheckStatus.PASS: 1.0, CheckStatus.WARN: 0.5, CheckStatus.FAIL: 0.0}
        scored = [weights[c.status] for c in self.checks if c.status in weights]
        self.quality = round(sum(scored) / len(scored), 3) if scored else 0.0
        usable = [s for s, c in self.sides.items() if c.usable]
        self.phase = CalPhase.COMPLETE if usable and not self.failure_reason else CalPhase.FAILED
        self._buf_t, self._buf_x = [], []

    # ------------------------------------------------------------------ #

    @property
    def status(self) -> CheckStatus:
        if not self.checks:
            return CheckStatus.SKIPPED
        return _worst([c.status for c in self.checks])

    def apply(self, data: np.ndarray) -> np.ndarray:
        """Bias-correct and scale a raw block. Force offsets are subtracted."""
        out = data.copy()
        for side in ("LEFT", "RIGHT"):
            sl = self.layout.side_slice(side)
            out[:, sl] = self.sides[side].apply(data[:, sl])
        for j, off in enumerate(self.force_offset):
            if off is not None:
                out[:, 12 + j] = np.maximum(0.0, data[:, 12 + j] - off)
        return out

    def metadata(self) -> dict:
        """The stored calibration record (the `device_calibrations.payload`)."""
        return {
            "calibration_version": CALIBRATION_VERSION,
            "phase": self.phase.value,
            "status": self.status.value,
            "quality": self.quality,
            "sampling_rate": {
                "declared_hz": self.declared_rate_hz,
                "measured_hz": None if self.measured_rate_hz is None else round(self.measured_rate_hz, 2),
            },
            "left_imu_offset": self.sides["LEFT"].as_dict(),
            "right_imu_offset": self.sides["RIGHT"].as_dict(),
            "force_offset": {
                fid: {"offset": self.force_offset[j] if j < len(self.force_offset) else None,
                      "noise": self.force_noise[j] if j < len(self.force_noise) else None,
                      "unit": self.layout.force_units[j]}
                for j, fid in enumerate(self.layout.force_ids)
            },
            "orientation": {
                side: {"neutral_gravity_unit": c.as_dict()["neutral_gravity_unit"],
                       "rotation_axis_unit": c.as_dict()["rotation_axis_unit"],
                       "placement": self.layout.imu_placements.get(side)}
                for side, c in self.sides.items()
            },
            "protocol": {"health_seconds": self.health_seconds,
                         "still_seconds": self.still_seconds,
                         "movement_seconds": self.movement_seconds},
            "health": self.health,
            "health_attempts": self.health_attempts,
            "failure_reason": self.failure_reason,
            # Session-time windows the result was computed from.
            "windows": self.windows,
            "thresholds": THRESHOLDS,
            "checks": [c.as_dict() for c in self.checks],
        }


def recompute(layout: ChannelLayout, declared_rate_hz: float, ts: np.ndarray, data: np.ndarray,
              windows: dict, measured_rate_hz: float | None, *, still_seconds: float,
              movement_seconds: float) -> DeviceCalibrator:
    """Recompute a stored calibration from raw samples and its recorded windows.

    `ts`/`data` are the session's stored raw samples (session time, raw
    channel values). Same code, same windows -> same offsets, so a stored
    calibration can be audited or re-run with a newer algorithm.
    """
    cal = DeviceCalibrator(layout, declared_rate_hz, still_seconds=still_seconds,
                           movement_seconds=movement_seconds)
    cal.measured_rate_hz = measured_rate_hz
    cal.windows = dict(windows)
    s0, s1 = windows["still"]
    m0, m1 = windows["movement"]
    still = data[(ts >= s0 - 1e-6) & (ts <= s1 + 1e-6)]
    msel = (ts >= m0 - 1e-6) & (ts <= m1 + 1e-6)
    cal._finalise(still, data[msel], ts[msel])
    return cal
