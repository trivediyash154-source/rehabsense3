"""Versioned feature extraction, shared by training (`ml/`) and inference.

The ML training code imports *this module*, so a model can only ever be
trained on exactly the features the backend computes at inference time. Any
change to the output (names, order, maths) must bump FEATURE_VERSION; model
bundles record the version they were trained with and the backend refuses to
run a bundle whose version differs.

Why orientation-invariant channels
----------------------------------
A public dataset's sensor axes, a different strap on a different day, and the
left vs right MPU6050 all have different orientations. Raw-axis features
(e.g. "mean of ax") change meaning when the sensor is rotated, which is one of
the largest sources of public-dataset -> hardware domain gap. Each IMU is
therefore converted to six channels that do not depend on how it is mounted:

    acc_norm    |a|                              (g)
    acc_vert    a . g_hat                        (g)   g_hat = window-mean gravity
    acc_horiz   |a - (a . g_hat) g_hat|          (g)
    gyro_norm   |w|                              (deg/s)
    gyro_vert   w . g_hat                        (deg/s)
    gyro_horiz  |w - (w . g_hat) g_hat|          (deg/s)

The cost is that posture (which way the segment points relative to gravity)
is discarded, which is what separates sitting from standing. The calibration
step recovers it: the wearer's neutral standing pose gives a gravity
direction g0 in each sensor's own frame, and posture features are measured
relative to it (`neutral_features`). Public datasets have no such step, so
training emulates it with one reserved standing recording per subject,
excluded from evaluation (see ml/rehabsense_ml/datasets). `ml/` benchmarks raw-axis vs invariant inputs, including a random
rotation robustness test, so this trade-off is measured rather than asserted.
"""

from __future__ import annotations

import numpy as np

FEATURE_VERSION = "inv-feat-v2"

INVARIANT_CHANNELS = ("acc_norm", "acc_vert", "acc_horiz", "gyro_norm", "gyro_vert", "gyro_horiz")
STAT_NAMES = (
    "mean", "std", "min", "max", "p10", "p25", "p50", "p75", "p90", "iqr", "rms", "mad",
    "skew", "kurt", "zcr", "dom_freq", "dom_frac", "spec_entropy",
    "band_0_1", "band_1_3", "band_3_6", "band_6_up", "ac_peak", "ac_lag",
)
CROSS_CHANNELS = ("acc_norm", "acc_vert", "gyro_norm", "gyro_vert")


def invariant_channels(imu: np.ndarray) -> np.ndarray:
    """(..., n, 6) raw [ax ay az gx gy gz] -> (..., n, 6) invariant channels."""
    acc = imu[..., 0:3]
    gyr = imu[..., 3:6]
    g = acc.mean(axis=-2, keepdims=True)
    g_hat = g / np.maximum(np.linalg.norm(g, axis=-1, keepdims=True), 1e-9)
    a_v = np.sum(acc * g_hat, axis=-1)
    a_h = np.linalg.norm(acc - a_v[..., None] * g_hat, axis=-1)
    w_v = np.sum(gyr * g_hat, axis=-1)
    w_h = np.linalg.norm(gyr - w_v[..., None] * g_hat, axis=-1)
    return np.stack(
        [np.linalg.norm(acc, axis=-1), a_v, a_h, np.linalg.norm(gyr, axis=-1), w_v, w_h],
        axis=-1,
    )


def _stats(x: np.ndarray, rate: float) -> np.ndarray:
    """x: (W, n, C) -> (W, C, K) statistics, vectorised across windows."""
    W, n, C = x.shape
    mean = x.mean(axis=1)
    std = x.std(axis=1)
    pct = np.percentile(x, [10, 25, 50, 75, 90], axis=1)  # (5, W, C)
    xc = x - mean[:, None, :]
    safe = np.maximum(std, 1e-9)
    skew = (xc ** 3).mean(axis=1) / safe ** 3
    kurt = (xc ** 4).mean(axis=1) / safe ** 4 - 3.0
    sign = np.signbit(xc)
    zcr = (sign[:, 1:, :] != sign[:, :-1, :]).mean(axis=1)

    nfft = int(2 ** np.ceil(np.log2(max(n, 64))))
    spec = np.abs(np.fft.rfft(xc, n=nfft, axis=1)) ** 2  # (W, F, C)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / rate)
    spec[:, 0, :] = 0.0
    total = np.maximum(spec.sum(axis=1), 1e-12)
    dom_idx = spec.argmax(axis=1)
    dom_freq = freqs[dom_idx]
    dom_frac = np.take_along_axis(spec, dom_idx[:, None, :], axis=1)[:, 0, :] / total
    p = spec / total[:, None, :]
    entropy = -(p * np.log(np.maximum(p, 1e-12))).sum(axis=1) / np.log(spec.shape[1])

    def band(lo, hi):
        sel = (freqs >= lo) & (freqs < hi)
        return spec[:, sel, :].sum(axis=1) / total

    nyq = rate / 2.0
    bands = [band(0.3, 1.0), band(1.0, 3.0), band(3.0, 6.0), band(6.0, nyq + 1e-9)]

    # Autocorrelation peak in 0.3-2.5 s: periodicity (steps, repetitions).
    ac = np.fft.irfft(np.abs(np.fft.rfft(xc, n=2 * nfft, axis=1)) ** 2, axis=1)[:, :n, :]
    ac = ac / np.maximum(ac[:, :1, :], 1e-12)
    lo_lag = max(1, int(0.3 * rate))
    hi_lag = min(n - 1, int(2.5 * rate))
    if hi_lag > lo_lag:
        seg = ac[:, lo_lag:hi_lag, :]
        ac_peak = seg.max(axis=1)
        ac_lag = (seg.argmax(axis=1) + lo_lag) / rate
    else:
        ac_peak = np.zeros((W, C))
        ac_lag = np.zeros((W, C))

    feats = [
        mean, std, x.min(axis=1), x.max(axis=1), pct[0], pct[1], pct[2], pct[3], pct[4],
        pct[3] - pct[1], np.sqrt((x ** 2).mean(axis=1)), np.abs(xc).mean(axis=1),
        skew, kurt, zcr, dom_freq, dom_frac, entropy, *bands, ac_peak, ac_lag,
    ]
    return np.stack(feats, axis=-1)  # (W, C, K)


NEUTRAL_NAMES = (
    "tilt_mean", "tilt_std", "tilt_min", "tilt_max",
    "acc_along_neutral_mean", "acc_along_neutral_std",
    "gyro_about_neutral_absmean", "gyro_about_neutral_std",
)


def neutral_features(imu: np.ndarray, g0: np.ndarray) -> np.ndarray:
    """Posture relative to the calibrated neutral pose.

    The invariant channels cannot tell a horizontal thigh from a vertical one,
    because they discard the sensor frame. The neutral gravity direction g0
    (measured while the wearer stands still during calibration, in the same
    sensor frame) restores that information without depending on how the
    sensor was mounted: rotate the sensor and g0 rotates with it, so these
    angles do not change.

    imu: (W, n, 6); g0: (W, 3) or (3,) unit vectors.
    """
    g0 = np.broadcast_to(np.asarray(g0, dtype=float), (len(imu), 3))
    acc = imu[..., 0:3]
    gyr = imu[..., 3:6]
    unit = acc / np.maximum(np.linalg.norm(acc, axis=-1, keepdims=True), 1e-9)
    cosang = np.clip(np.einsum("wnk,wk->wn", unit, g0), -1.0, 1.0)
    tilt = np.degrees(np.arccos(cosang))
    along = np.einsum("wnk,wk->wn", acc, g0)
    about = np.einsum("wnk,wk->wn", gyr, g0)
    return np.stack([
        tilt.mean(1), tilt.std(1), tilt.min(1), tilt.max(1),
        along.mean(1), along.std(1), np.abs(about).mean(1), about.std(1),
    ], axis=1)


def side_features(imu: np.ndarray, rate: float, g0: np.ndarray) -> np.ndarray:
    """(W, n, 6) raw IMU windows + neutral gravity -> (W, 6*K + 1 + 8) features."""
    inv = invariant_channels(imu)
    st = _stats(inv, rate).reshape(len(imu), -1)
    jerk = np.diff(inv[..., 0], axis=1) * rate
    jerk_rms = np.sqrt((jerk ** 2).mean(axis=1, keepdims=True))
    return np.concatenate([st, jerk_rms, neutral_features(imu, g0)], axis=1)


def side_feature_names(prefix: str) -> list[str]:
    names = [f"{prefix}_{c}_{s}" for c in INVARIANT_CHANNELS for s in STAT_NAMES]
    return names + [f"{prefix}_acc_norm_jerk_rms"] + [f"{prefix}_{n}" for n in NEUTRAL_NAMES]


def cross_features(left: np.ndarray, right: np.ndarray, rate: float) -> np.ndarray:
    """Left/right relationship features from raw (W, n, 6) windows of each side."""
    li, ri = invariant_channels(left), invariant_channels(right)
    W, n, _ = li.shape
    max_lag = min(n - 1, int(1.0 * rate))
    out = []
    for name in CROSS_CHANNELS:
        c = INVARIANT_CHANNELS.index(name)
        a = li[..., c] - li[..., c].mean(axis=1, keepdims=True)
        b = ri[..., c] - ri[..., c].mean(axis=1, keepdims=True)
        denom = np.maximum(np.sqrt((a ** 2).sum(axis=1) * (b ** 2).sum(axis=1)), 1e-12)
        nfft = int(2 ** np.ceil(np.log2(2 * n)))
        xc = np.fft.irfft(np.fft.rfft(a, nfft, axis=1) * np.conj(np.fft.rfft(b, nfft, axis=1)),
                          nfft, axis=1)
        lags = np.concatenate([xc[:, : max_lag + 1], xc[:, -max_lag:]], axis=1) / denom[:, None]
        lag_values = np.concatenate([np.arange(max_lag + 1), -np.arange(max_lag, 0, -1)]) / rate
        idx = lags.argmax(axis=1)
        out += [lags.max(axis=1), lag_values[idx], lags[:, 0]]
    lstd = li.std(axis=1)
    rstd = ri.std(axis=1)
    out += [np.log((lstd[:, c] + 1e-6) / (rstd[:, c] + 1e-6)) for c in range(6)]
    return np.stack(out, axis=1)


def cross_feature_names() -> list[str]:
    names = []
    for c in CROSS_CHANNELS:
        names += [f"lr_{c}_xcorr_max", f"lr_{c}_xcorr_lag_s", f"lr_{c}_corr0"]
    return names + [f"lr_{c}_log_std_ratio" for c in INVARIANT_CHANNELS]


def bilateral_features(left: np.ndarray, right: np.ndarray, rate: float,
                       g0_left: np.ndarray, g0_right: np.ndarray) -> np.ndarray:
    return np.concatenate(
        [side_features(left, rate, g0_left), side_features(right, rate, g0_right),
         cross_features(left, right, rate)],
        axis=1,
    )


def bilateral_feature_names() -> list[str]:
    return side_feature_names("left") + side_feature_names("right") + cross_feature_names()


def raw_axis_features(imu: np.ndarray, rate: float) -> np.ndarray:
    """Orientation-*dependent* comparison features (benchmarks only)."""
    return _stats(imu, rate).reshape(len(imu), -1)
