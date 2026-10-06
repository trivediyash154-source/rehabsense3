"""Window extraction for training, using the backend's resampling.

Windows are cut *inside* one recording only. The `groups` array carries the
subject of every window, and every split in this package is a GroupKFold on
it: no subject appears on both sides of a split, and because a recording
belongs to exactly one subject, neither does any recording.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rehabsense_ml.datasets import Recording


@dataclass
class WindowSet:
    left: np.ndarray              # (W, n, 6)
    right: np.ndarray | None      # (W, n, 6) or None for single-IMU sets
    y: np.ndarray                 # (W,) labels
    groups: np.ndarray            # (W,) subject ids
    rate_hz: float
    window_s: float
    g0_left: np.ndarray           # (W, 3) neutral gravity, sensor frame
    g0_right: np.ndarray | None

    def __len__(self) -> int:
        return len(self.y)

    def subset(self, idx: np.ndarray) -> "WindowSet":
        return WindowSet(self.left[idx], None if self.right is None else self.right[idx],
                         self.y[idx], self.groups[idx], self.rate_hz, self.window_s,
                         self.g0_left[idx], None if self.g0_right is None else self.g0_right[idx])


def make_windows(recs: list[Recording], window_s: float, stride_s: float,
                 bilateral: bool) -> WindowSet:
    rate = recs[0].rate_hz
    n = int(round(window_s * rate))
    step = max(1, int(round(stride_s * rate)))
    L, R, Y, G, NL, NR = [], [], [], [], [], []
    for r in recs:
        if bilateral and r.right is None:
            raise ValueError("bilateral windows requested from a single-IMU recording")
        total = len(r.left)
        for s in range(0, total - n + 1, step):
            L.append(r.left[s:s + n])
            if bilateral:
                R.append(r.right[s:s + n])
            Y.append(r.label)
            G.append(r.subject)
            NL.append(r.neutral_left)
            if bilateral:
                NR.append(r.neutral_right)
    return WindowSet(np.stack(L), np.stack(R) if bilateral else None,
                     np.array(Y), np.array(G), rate, window_s,
                     np.stack(NL), np.stack(NR) if bilateral else None)


def single_side_from_bilateral(recs: list[Recording]) -> list[Recording]:
    """Each leg of a bilateral recording as its own single-IMU recording.

    These are two *real* sensors, so using each one alone is legitimate (it is
    the opposite of mirroring one sensor into a fake second side).
    """
    out = []
    for r in recs:
        out.append(Recording(r.subject, r.label, r.source_activity, r.rate_hz, r.left,
                             meta={**r.meta, "side": "left_leg"}, neutral_left=r.neutral_left))
        out.append(Recording(r.subject, r.label, r.source_activity, r.rate_hz, r.right,
                             meta={**r.meta, "side": "right_leg"}, neutral_left=r.neutral_right))
    return out
