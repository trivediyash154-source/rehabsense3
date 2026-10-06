"""Robustness perturbations, applied to raw test windows *before* features.

Each one models a specific way the RehabSense device differs from the
training data, so a robustness number answers a concrete question:

    rotation      the IMU is strapped on at a different orientation
    noise_x3      a noisier sensor (MPU6050 vs Xsens)
    gyro_bias     residual gyro bias after calibration (+-3 deg/s)
    rate_5pct     the device clock runs 5% off its declared rate
    accel_gain    accelerometer scale error (+-5%)
"""

from __future__ import annotations

import numpy as np


def random_rotations(n: int, rng: np.random.Generator) -> np.ndarray:
    q = rng.normal(size=(n, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    w, x, y, z = q.T
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
    ], axis=1)


# Every perturbation takes and returns (imu, g0): the neutral pose is measured
# by the same sensor, so a remounted sensor also has a rotated neutral pose.

def rotate(imu: np.ndarray, g0: np.ndarray, rng):
    R = random_rotations(len(imu), rng)
    out = imu.copy()
    out[..., 0:3] = np.einsum("wij,wnj->wni", R, imu[..., 0:3])
    out[..., 3:6] = np.einsum("wij,wnj->wni", R, imu[..., 3:6])
    return out, np.einsum("wij,wj->wi", R, g0)


def noise(imu: np.ndarray, g0, rng, scale=3.0):
    out = imu.copy()
    out[..., 0:3] += rng.normal(0, 0.01 * scale, out[..., 0:3].shape)
    out[..., 3:6] += rng.normal(0, 0.5 * scale, out[..., 3:6].shape)
    return out, g0


def gyro_bias(imu: np.ndarray, g0, rng, dps=3.0):
    out = imu.copy()
    out[..., 3:6] += rng.uniform(-dps, dps, (len(imu), 1, 3))
    return out, g0


def accel_gain(imu: np.ndarray, g0, rng, pct=0.05):
    out = imu.copy()
    out[..., 0:3] *= rng.uniform(1 - pct, 1 + pct, (len(imu), 1, 3))
    return out, g0


def rate_error(imu: np.ndarray, g0, rng, pct=0.05):
    """Resample as if the device clock ran `pct` fast (time-stretch)."""
    n = imu.shape[1]
    src = np.arange(n)
    dst = np.clip(np.arange(n) * (1 + pct), 0, n - 1)
    lo = np.floor(dst).astype(int)
    hi = np.minimum(lo + 1, n - 1)
    frac = (dst - lo)[None, :, None]
    return imu[:, lo, :] * (1 - frac) + imu[:, hi, :] * frac, g0


PERTURBATIONS = {
    "rotation": rotate,
    "noise_x3": noise,
    "gyro_bias": gyro_bias,
    "accel_gain": accel_gain,
    "rate_5pct": rate_error,
}


def augment_device_like(imu: np.ndarray, g0: np.ndarray, rng):
    """Training-time domain randomisation toward MPU6050-like data.

    Moderate noise (2x), residual gyro bias and accelerometer gain error,
    applied to a copy of the training windows. Never applied to test windows.
    """
    a, g = noise(imu, g0, rng, scale=2.0)
    a, g = gyro_bias(a, g, rng, dps=2.0)
    a, g = accel_gain(a, g, rng, pct=0.03)
    return a, g
