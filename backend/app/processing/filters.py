"""Digital filters.

The documented pipeline calls for a 2nd-order Butterworth low-pass at ~5 Hz.
scipy has no wheel for the Python running here and fails to build, so the
filter is implemented directly as a biquad derived through the bilinear
transform. That is the same filter, not an approximation of it: the transfer
function below is the standard RBJ/Butterworth low-pass with Q = 1/sqrt(2),
which is precisely what `scipy.signal.butter(2, ...)` produces.

`tests/test_filters.py` verifies the magnitude response against the analytic
Butterworth response, so the substitution is checked rather than assumed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Biquad:
    """Direct-form II transposed biquad section."""

    b0: float
    b1: float
    b2: float
    a1: float
    a2: float
    _z1: float = field(default=0.0, init=False)
    _z2: float = field(default=0.0, init=False)
    _primed: bool = field(default=False, init=False)

    def reset(self, value: float = 0.0) -> None:
        """Prime the delay line so the filter starts at `value`, not at zero.

        Without this, every stream begins with a spurious ramp from 0 to the
        first sample — which the repetition detector would read as movement.
        """
        self._z1 = value * (1.0 - self.b0)
        self._z2 = value * (self.b1 + self.b2 - self.b0 * (self.a1 + self.a2))
        self._primed = True

    def __call__(self, x: float) -> float:
        if not self._primed:
            self.reset(x)
        y = self.b0 * x + self._z1
        self._z1 = self.b1 * x - self.a1 * y + self._z2
        self._z2 = self.b2 * x - self.a2 * y
        return y

    def response_db(self, freq_hz: float, fs: float) -> float:
        """Magnitude response in dB at `freq_hz`, for verification."""
        w = 2.0 * math.pi * freq_hz / fs
        cos1, sin1 = math.cos(w), math.sin(w)
        cos2, sin2 = math.cos(2 * w), math.sin(2 * w)
        num_re = self.b0 + self.b1 * cos1 + self.b2 * cos2
        num_im = -(self.b1 * sin1 + self.b2 * sin2)
        den_re = 1.0 + self.a1 * cos1 + self.a2 * cos2
        den_im = -(self.a1 * sin1 + self.a2 * sin2)
        num = math.hypot(num_re, num_im)
        den = math.hypot(den_re, den_im)
        if den == 0:
            return float("inf")
        return 20.0 * math.log10(max(num / den, 1e-12))


def butterworth_lowpass(cutoff_hz: float, sample_rate_hz: float) -> Biquad:
    """2nd-order Butterworth low-pass via the bilinear transform.

    Q = 1/sqrt(2) is what makes it Butterworth (maximally flat passband)
    rather than any other 2nd-order shape.
    """
    if cutoff_hz <= 0 or sample_rate_hz <= 0:
        raise ValueError("cutoff and sample rate must be positive")
    nyquist = sample_rate_hz / 2.0
    if cutoff_hz >= nyquist:
        raise ValueError("cutoff must be below the Nyquist frequency")

    w0 = 2.0 * math.pi * cutoff_hz / sample_rate_hz
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    q = 1.0 / math.sqrt(2.0)
    alpha = sin_w0 / (2.0 * q)

    b0 = (1.0 - cos_w0) / 2.0
    b1 = 1.0 - cos_w0
    b2 = (1.0 - cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha

    return Biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


class VectorLowpass:
    """One independent biquad per named channel."""

    def __init__(self, channels: tuple[str, ...], cutoff_hz: float, sample_rate_hz: float):
        self._filters = {
            name: butterworth_lowpass(cutoff_hz, sample_rate_hz) for name in channels
        }

    def __call__(self, values: dict[str, float]) -> dict[str, float]:
        return {
            name: self._filters[name](value) if name in self._filters else value
            for name, value in values.items()
        }
