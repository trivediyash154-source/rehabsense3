"""Canonical channel layout for the dual-IMU + force device.

LEFT and RIGHT are kept as separate channel groups end to end. They are never
averaged into "one sensor", because every bilateral metric depends on knowing
which side a number came from.

Array layout (one row per device tick):

    0..5    left  ax ay az gx gy gz     (g, deg/s)
    6..11   right ax ay az gx gy gz     (g, deg/s)
    12..    force channels, in declared order (declared unit)

A missing reading is NaN, never zero: zero is a valid acceleration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

IMU_AXES = ("ax", "ay", "az", "gx", "gy", "gz")
SIDES = ("LEFT", "RIGHT")
LEFT = slice(0, 6)
RIGHT = slice(6, 12)
ACC = slice(0, 3)
GYRO = slice(3, 6)


@dataclass(frozen=True)
class ChannelLayout:
    force_ids: tuple[str, ...] = ()
    force_sides: tuple[str | None, ...] = ()
    force_units: tuple[str, ...] = ()
    imu_sides: tuple[str, ...] = SIDES
    imu_placements: dict[str, str] = field(default_factory=dict)

    @property
    def n_force(self) -> int:
        return len(self.force_ids)

    @property
    def n_channels(self) -> int:
        return 12 + self.n_force

    @property
    def names(self) -> list[str]:
        names = [f"left_{a}" for a in IMU_AXES] + [f"right_{a}" for a in IMU_AXES]
        # The unit is part of the name, so a raw ADC reading can never be
        # mistaken for calibrated force: force_<id>_adc_norm vs force_<id>_N.
        units = self.force_units or tuple("adc_norm" for _ in self.force_ids)
        return names + [f"force_{fid}_{u}" for fid, u in zip(self.force_ids, units)]

    def side_slice(self, side: str) -> slice:
        return LEFT if side == "LEFT" else RIGHT

    def force_index(self, i: int) -> int:
        return 12 + i

    def force_channels_for(self, side: str | None) -> list[int]:
        return [i for i, s in enumerate(self.force_sides) if s == side]

    def as_dict(self) -> dict:
        return {
            "names": self.names,
            "force_ids": list(self.force_ids),
            "force_sides": list(self.force_sides),
            "force_units": list(self.force_units),
            "imu_sides": list(self.imu_sides),
            "imu_placements": dict(self.imu_placements),
            "units": {"acc": "g", "gyro": "deg/s"},
        }

    @classmethod
    def from_hello(cls, hello) -> "ChannelLayout":
        return cls(
            force_ids=tuple(c.id for c in hello.force_channels),
            force_sides=tuple(c.side.value if c.side else None for c in hello.force_channels),
            force_units=tuple(c.unit.value for c in hello.force_channels),
            imu_sides=tuple(i.side.value for i in hello.imus),
            imu_placements={i.side.value: i.placement.value for i in hello.imus},
        )


def samples_to_array(samples, layout: ChannelLayout) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert validated DualSample objects to (ts, seq, data[n, channels]).

    Missing IMUs and missing force values become NaN.
    """
    n = len(samples)
    data = np.full((n, layout.n_channels), np.nan, dtype=np.float64)
    ts = np.empty(n, dtype=np.float64)
    seq = np.empty(n, dtype=np.int64)
    for i, s in enumerate(samples):
        ts[i] = s.ts
        seq[i] = s.seq
        if s.imu_left is not None:
            r = s.imu_left
            data[i, 0:6] = (r.ax, r.ay, r.az, r.gx, r.gy, r.gz)
        if s.imu_right is not None:
            r = s.imu_right
            data[i, 6:12] = (r.ax, r.ay, r.az, r.gx, r.gy, r.gz)
        for j in range(min(layout.n_force, len(s.force))):
            v = s.force[j]
            if v is not None:
                data[i, 12 + j] = v
    return ts, seq, data
