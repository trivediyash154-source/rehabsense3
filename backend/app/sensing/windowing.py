"""Sliding windows and resampling.

The window length, stride and model input rate are configuration (and are
stored with every model), never constants buried in code:

    sampling_rate  what the device actually delivers (measured)
    model_rate     what the model was trained at (from its bundle)
    window_s       seconds per inference window (from its bundle)
    stride_s       seconds between inferences (server configuration)

Resampling is linear interpolation onto a uniform grid. It is applied to the
hardware stream to reach the model's rate; it is also what absorbs small
timing jitter from the device.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

PREPROCESSING_VERSION = "prep-v2"
# A window with more missing samples than this is not classified.
MAX_MISSING_FRACTION = 0.10


def resample_uniform(ts: np.ndarray, data: np.ndarray, rate_hz: float,
                     t_start: float | None = None, n: int | None = None) -> np.ndarray:
    """Linear interpolation of each column onto a uniform grid.

    NaNs in a column are bridged by interpolation from neighbouring valid
    samples; a column with fewer than two valid samples comes back all-NaN.
    """
    if t_start is None:
        t_start = float(ts[0])
    if n is None:
        n = int(np.floor((ts[-1] - t_start) * rate_hz)) + 1
    grid = t_start + np.arange(n) / rate_hz
    out = np.full((n, data.shape[1]), np.nan)
    for c in range(data.shape[1]):
        col = data[:, c]
        ok = ~np.isnan(col)
        if ok.sum() >= 2:
            out[:, c] = np.interp(grid, ts[ok], col[ok])
    return out


def moving_average(data: np.ndarray, k: int) -> np.ndarray:
    """Centred k-sample moving average per column (NaN-aware), edges shrink."""
    if k <= 1:
        return data
    out = np.empty_like(data, dtype=float)
    kernel = np.ones(k)
    for c in range(data.shape[1]):
        col = data[:, c]
        ok = np.isfinite(col)
        num = np.convolve(np.where(ok, col, 0.0), kernel, mode="same")
        den = np.convolve(ok.astype(float), kernel, mode="same")
        out[:, c] = np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)
    return out


def prepare_model_input(ts: np.ndarray, data: np.ndarray, rate_out: float,
                        t_start: float | None = None, n: int | None = None) -> np.ndarray:
    """THE single path from sensor samples to model-rate samples.

    Used by the live hardware inference *and* by ml/ when it downsamples a
    public dataset (PAMAP2 100 Hz -> 25 Hz), so the device stream and the
    training data go through identical code:

      1. estimate the source rate from the timestamps
      2. anti-alias: centred moving average over round(src/rate_out) samples
         (a no-op when the source is already at the model rate)
      3. linear interpolation onto the model's uniform grid

    Without step 2, a 100 Hz MPU6050 stream decimated to 25 Hz would alias
    content above 12.5 Hz into the band the model uses -- data the model
    never saw in training.
    """
    if len(ts) < 2:
        return np.full((n or 0, data.shape[1]), np.nan)
    dt = np.diff(ts)
    dt = dt[dt > 0]
    src_rate = 1.0 / float(np.median(dt)) if len(dt) else rate_out
    k = int(round(src_rate / rate_out))
    return resample_uniform(ts, moving_average(data, k), rate_out, t_start=t_start, n=n)


def window_starts(n_samples: int, window: int, stride: int) -> list[int]:
    if n_samples < window:
        return []
    return list(range(0, n_samples - window + 1, stride))


@dataclass
class SlidingWindowBuffer:
    """Accumulates device samples; emits a window every `stride_s`."""

    window_s: float
    stride_s: float
    n_channels: int
    max_seconds: float = 30.0

    _ts: deque = field(default_factory=deque, init=False)
    _rows: deque = field(default_factory=deque, init=False)
    _next_emit: float | None = field(default=None, init=False)

    def extend(self, ts: np.ndarray, data: np.ndarray) -> None:
        for t, row in zip(ts, data):
            self._ts.append(float(t))
            self._rows.append(row)
        if not self._ts:
            return
        horizon = self._ts[-1] - max(self.max_seconds, self.window_s * 2)
        while self._ts and self._ts[0] < horizon:
            self._ts.popleft()
            self._rows.popleft()
        if self._next_emit is None:
            self._next_emit = self._ts[0] + self.window_s

    def pop_windows(self) -> list[tuple[float, float, np.ndarray, np.ndarray]]:
        """Return (t_start, t_end, ts, data) for every window now complete."""
        out = []
        if self._next_emit is None or not self._ts:
            return out
        ts = np.fromiter(self._ts, dtype=float)
        rows = np.vstack(self._rows) if self._rows else np.empty((0, self.n_channels))
        while self._next_emit <= ts[-1]:
            t_end = self._next_emit
            t_start = t_end - self.window_s
            sel = (ts > t_start - 1e-9) & (ts <= t_end + 1e-9)
            if sel.sum() >= 2:
                out.append((t_start, t_end, ts[sel], rows[sel]))
            self._next_emit += self.stride_s
        return out

    def recent(self, seconds: float) -> tuple[np.ndarray, np.ndarray]:
        if not self._ts:
            return np.empty(0), np.empty((0, self.n_channels))
        ts = np.fromiter(self._ts, dtype=float)
        rows = np.vstack(self._rows)
        sel = ts >= ts[-1] - seconds
        return ts[sel], rows[sel]
