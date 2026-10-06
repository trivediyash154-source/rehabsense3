"""Stream integrity for a single dual-IMU device.

Both IMUs and the force channels arrive inside the same sample with one
device timestamp, so they share a clock by construction. What still has to be
verified, not assumed:

  * ordering      samples must advance in `seq` and in `ts`
  * duplicates    a retransmitted sample must not be counted twice
  * gaps          a jump in `seq` is lost samples
  * sampling rate measured from device timestamps vs the declared rate
  * jitter        spread of inter-sample intervals
  * clock drift   device clock vs server clock, from packet arrival times
  * latency       arrival delay *relative to the best observed* delay

On latency: true one-way latency needs synchronised clocks, which an ESP32 on
Wi-Fi does not have. What is measurable is how much later than its fastest
packet each packet arrived (`arrival - device_ts - min(arrival - device_ts)`).
That is reported as `relative_latency_ms` and labelled as such.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

# A device rate outside this tolerance of its declaration is reported.
RATE_TOLERANCE = 0.05
# No real oscillator drifts this much: a larger device-vs-server rate
# difference means the stream is not real-time (replay, speed-up, or a
# buffered burst), so it is reported as such and never as clock drift.
MAX_PLAUSIBLE_DRIFT_PPM = 2000.0
# Identical consecutive readings on all six axes for this many samples means
# the IMU is frozen (a hung I2C bus often returns the last value forever).
FROZEN_RUN = 25


def _pct(values, q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), q))


@dataclass
class StreamMonitor:
    declared_rate_hz: float
    # Full-scale ranges declared per IMU (MPU6050 defaults: +-4 g, +-500 dps).
    accel_range_g: dict = field(default_factory=lambda: {"LEFT": 4.0, "RIGHT": 4.0})
    gyro_range_dps: dict = field(default_factory=lambda: {"LEFT": 500.0, "RIGHT": 500.0})
    force_units: tuple = ()

    received: int = 0
    accepted: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    timestamp_anomalies: int = 0
    gaps: int = 0
    missing_samples: int = 0
    left_missing: int = 0
    right_missing: int = 0
    force_missing: int = 0
    packets: int = 0

    last_seq: int | None = None
    last_ts: float | None = None
    first_ts: float | None = None
    first_seq: int | None = None

    _dts: deque = field(default_factory=lambda: deque(maxlen=2000))
    _seen: set = field(default_factory=set)
    _seen_order: deque = field(default_factory=deque)
    _offsets: deque = field(default_factory=lambda: deque(maxlen=600))   # (device_ts, arrival)
    _relative_latency_ms: deque = field(default_factory=lambda: deque(maxlen=600))
    _frozen: dict = field(default_factory=lambda: {"LEFT": 0, "RIGHT": 0})
    _last_vals: dict = field(default_factory=lambda: {"LEFT": None, "RIGHT": None})
    frozen_flags: dict = field(default_factory=lambda: {"LEFT": False, "RIGHT": False})
    # Abnormal values: at (>= 98% of) full scale = saturated, i.e. the true
    # value is unknown; beyond full scale = physically impossible for the
    # configured sensor, i.e. a corrupt reading.
    saturated: dict = field(default_factory=lambda: {"LEFT": 0, "RIGHT": 0})
    out_of_range: dict = field(default_factory=lambda: {"LEFT": 0, "RIGHT": 0})
    force_out_of_range: int = 0
    force_received: list = field(default_factory=list)   # per channel, non-null readings

    def observe(self, ts: np.ndarray, seq: np.ndarray, data: np.ndarray,
                arrival: float) -> np.ndarray:
        """Inspect one packet. Returns a boolean mask of samples to keep.

        Duplicates, out-of-order samples and samples whose timestamp does not
        advance are dropped here, so nothing downstream ever sees time going
        backwards.
        """
        self.packets += 1
        n = len(ts)
        self.received += n
        keep = np.zeros(n, dtype=bool)

        for i in range(n):
            s, t = int(seq[i]), float(ts[i])
            if self.last_seq is not None:
                if s <= self.last_seq and t <= (self.last_ts or t):
                    # Already seen -> a retransmit (duplicate). Never seen ->
                    # a sample that arrived after later ones (out of order);
                    # it stays counted as missing, because the stream has
                    # already moved past its time.
                    if s in self._seen:
                        self.duplicates += 1
                    else:
                        self.out_of_order += 1
                    continue
                if s < self.last_seq:
                    # seq went backwards but time advanced: a device reboot.
                    # Accept and restart sequence tracking rather than drop
                    # the rest of the session.
                    self.last_seq = None
            if self.last_ts is not None and t <= self.last_ts:
                self.timestamp_anomalies += 1
                continue

            if self.last_seq is not None and s > self.last_seq + 1:
                self.gaps += 1
                self.missing_samples += s - self.last_seq - 1
            if self.last_ts is not None:
                self._dts.append(t - self.last_ts)
            if self.first_ts is None:
                self.first_ts, self.first_seq = t, s

            self.last_seq, self.last_ts = s, t
            self._seen.add(s)
            self._seen_order.append(s)
            if len(self._seen_order) > 5000:
                self._seen.discard(self._seen_order.popleft())
            keep[i] = True

        kept = data[keep]
        if len(kept):
            self.accepted += len(kept)
            left_nan = np.isnan(kept[:, 0:6]).any(axis=1)
            right_nan = np.isnan(kept[:, 6:12]).any(axis=1)
            self.left_missing += int(left_nan.sum())
            self.right_missing += int(right_nan.sum())
            if kept.shape[1] > 12:
                self.force_missing += int(np.isnan(kept[:, 12:]).any(axis=1).sum())
                ok = (~np.isnan(kept[:, 12:])).sum(axis=0)
                if not self.force_received:
                    self.force_received = [0] * len(ok)
                self.force_received = [a + int(b) for a, b in zip(self.force_received, ok)]
            self._track_frozen("LEFT", kept[:, 0:6])
            self._track_frozen("RIGHT", kept[:, 6:12])
            self._check_ranges(kept)

            last_device_ts = float(ts[keep][-1])
            self._offsets.append((last_device_ts, arrival))
            offset = arrival - last_device_ts
            best = min(a - d for d, a in self._offsets)
            self._relative_latency_ms.append(max(0.0, (offset - best) * 1000.0))
        return keep

    def _check_ranges(self, kept: np.ndarray) -> None:
        for side, sl in (("LEFT", slice(0, 6)), ("RIGHT", slice(6, 12))):
            block = kept[:, sl]
            ok = ~np.isnan(block).any(axis=1)
            if not ok.any():
                continue
            acc = np.abs(block[ok, 0:3])
            gyr = np.abs(block[ok, 3:6])
            ar, gr = self.accel_range_g[side], self.gyro_range_dps[side]
            sat = (acc >= 0.98 * ar).any(axis=1) | (gyr >= 0.98 * gr).any(axis=1)
            bad = (acc > 1.05 * ar).any(axis=1) | (gyr > 1.05 * gr).any(axis=1)
            self.saturated[side] += int((sat & ~bad).sum())
            self.out_of_range[side] += int(bad.sum())
        for j, unit in enumerate(self.force_units):
            if unit == "adc_norm" and kept.shape[1] > 12 + j:
                col = kept[:, 12 + j]
                col = col[np.isfinite(col)]
                self.force_out_of_range += int(((col < -0.01) | (col > 1.01)).sum())

    def _track_frozen(self, side: str, block: np.ndarray) -> None:
        for row in block:
            if np.isnan(row).any():
                continue
            prev = self._last_vals[side]
            if prev is not None and np.array_equal(prev, row):
                self._frozen[side] += 1
            else:
                self._frozen[side] = 0
            self._last_vals[side] = row
        self.frozen_flags[side] = self._frozen[side] >= FROZEN_RUN

    # ------------------------------------------------------------------ #

    @property
    def measured_rate_hz(self) -> float | None:
        """Rate from the median inter-sample interval (robust to gaps)."""
        if len(self._dts) < 10:
            return None
        median = float(np.median(np.asarray(self._dts)))
        return None if median <= 0 else 1.0 / median

    @property
    def effective_rate_hz(self) -> float | None:
        """Samples actually received per second of device time.

        Unlike the median-interval rate, this includes every lost sample: a
        100 Hz stream that loses 2% of its samples reads ~98 Hz here.
        """
        if self.first_ts is None or self.last_ts is None or self.last_ts <= self.first_ts:
            return None
        return (self.accepted - 1) / (self.last_ts - self.first_ts)

    @property
    def jitter_ms(self) -> float | None:
        if len(self._dts) < 10:
            return None
        return float(np.std(np.asarray(self._dts)) * 1000.0)

    @property
    def clock_drift_ppm(self) -> float | None:
        """Device clock rate relative to the server clock, in ppm.

        Slope of arrival time against device time, using the lower envelope
        (fastest packets) so network queueing does not masquerade as drift.
        Needs >= 30 s of data; shorter spans are dominated by jitter.
        """
        if len(self._offsets) < 30:
            return None
        pts = np.asarray(self._offsets)
        span = pts[-1, 0] - pts[0, 0]
        if span < 30.0:
            return None
        # Lower envelope: per 5 s bucket, the packet with the smallest delay.
        buckets: dict[int, tuple[float, float]] = {}
        for d, a in pts:
            key = int((d - pts[0, 0]) // 5.0)
            off = a - d
            if key not in buckets or off < buckets[key][1] - buckets[key][0]:
                buckets[key] = (d, a)
        if len(buckets) < 4:
            return None
        env = np.asarray(sorted(buckets.values()))
        slope = np.polyfit(env[:, 0], env[:, 1], 1)[0]
        return float((slope - 1.0) * 1e6)

    def clock(self) -> dict:
        """The four time bases, kept apart.

        DEVICE_TIME            sample `ts`, the ESP32's esp_timer (monotonic)
        SERVER_RECEIVE_TIME    wall clock when the packet arrived here
        SERVER_PROCESSING_TIME perf_counter stage latencies (`latency` block)
        FRONTEND_DISPLAY_TIME  browser clock when rendered (measured client-side)

        Measured here: device-to-server offset (lower bound: includes the
        minimum one-way network delay, which cannot be separated without a
        round-trip exchange), drift (device clock rate vs server clock),
        sample jitter and packet arrival delay relative to the fastest packet.
        """
        pts = np.asarray(self._offsets) if self._offsets else np.empty((0, 2))
        offset = float(np.min(pts[:, 1] - pts[:, 0])) if len(pts) else None
        span = float(pts[-1, 0] - pts[0, 0]) if len(pts) > 1 else 0.0
        drift = self.clock_drift_ppm
        if drift is None:
            status = "INSUFFICIENT_DATA"
            note = "Drift needs >= 30 s of streaming; offset/arrival delay are preliminary."
        elif abs(drift) > MAX_PLAUSIBLE_DRIFT_PPM:
            status = "NOT_REAL_TIME"
            note = ("Device time and server time advance at very different rates: a replayed, "
                    "sped-up or buffered stream. This is NOT evidence of physical clock drift.")
        else:
            status = "ESTABLISHED"
            note = ("Offset is a lower bound (includes the minimum network delay). Drift from the "
                    "lower envelope of arrival times.")
        lat = list(self._relative_latency_ms)
        return {
            "time_bases": ["DEVICE_TIME", "SERVER_RECEIVE_TIME", "SERVER_PROCESSING_TIME",
                           "FRONTEND_DISPLAY_TIME"],
            "sync_status": status,
            "device_to_server_offset_s": None if offset is None else round(offset, 6),
            "drift_ppm": None if drift is None or status == "NOT_REAL_TIME" else round(drift, 1),
            "device_vs_server_rate_ppm": None if drift is None else round(drift, 1),
            "observed_span_s": round(span, 3),
            "sample_jitter_ms": None if self.jitter_ms is None else round(self.jitter_ms, 3),
            "packet_arrival_delay_ms": {
                "p50": None if not lat else round(_pct(lat, 50), 2),
                "p95": None if not lat else round(_pct(lat, 95), 2),
                "max": None if not lat else round(max(lat), 2),
            },
            "note": note,
        }

    @property
    def rate_ok(self) -> bool | None:
        rate = self.measured_rate_hz
        if rate is None:
            return None
        return abs(rate - self.declared_rate_hz) / self.declared_rate_hz <= RATE_TOLERANCE

    @property
    def loss_ratio(self) -> float:
        expected = self.accepted + self.missing_samples
        return 0.0 if expected == 0 else self.missing_samples / expected

    def side_available_ratio(self, side: str) -> float:
        if self.accepted == 0:
            return 0.0
        missing = self.left_missing if side == "LEFT" else self.right_missing
        return 1.0 - missing / self.accepted

    def as_dict(self) -> dict:
        rate = self.measured_rate_hz
        lat = list(self._relative_latency_ms)
        eff = self.effective_rate_hz
        return {
            "declared_rate_hz": self.declared_rate_hz,
            # Rate implied by the typical interval between consecutive samples.
            "measured_rate_hz": None if rate is None else round(rate, 3),
            # Samples actually received per device second, losses included.
            "effective_rate_hz": None if eff is None else round(eff, 3),
            "force_available_ratio": [round(r / self.accepted, 4) if self.accepted else 0.0
                                      for r in self.force_received],
            "rate_ok": self.rate_ok,
            "jitter_ms": None if self.jitter_ms is None else round(self.jitter_ms, 3),
            "clock_drift_ppm": (
                None if self.clock_drift_ppm is None else round(self.clock_drift_ppm, 1)
            ),
            "samples_received": self.received,
            "samples_accepted": self.accepted,
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "timestamp_anomalies": self.timestamp_anomalies,
            "gaps": self.gaps,
            "missing_samples": self.missing_samples,
            "loss_ratio": round(self.loss_ratio, 4),
            "left_available_ratio": round(self.side_available_ratio("LEFT"), 4),
            "right_available_ratio": round(self.side_available_ratio("RIGHT"), 4),
            "left_frozen": self.frozen_flags["LEFT"],
            "right_frozen": self.frozen_flags["RIGHT"],
            "force_missing": self.force_missing,
            "saturated_samples": dict(self.saturated),
            "out_of_range_samples": dict(self.out_of_range),
            "force_out_of_range": self.force_out_of_range,
            "packets": self.packets,
            "clock": self.clock(),
            "relative_latency_ms": {
                "p50": None if not lat else round(_pct(lat, 50), 1),
                "p95": None if not lat else round(_pct(lat, 95), 1),
                "note": "Arrival delay relative to the fastest observed packet; "
                        "absolute one-way latency needs synchronised clocks.",
            },
        }


def is_finite_number(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)
