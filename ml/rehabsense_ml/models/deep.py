"""Compact sensor-fusion networks for the dual-IMU (+ force) layout.

    LEFT  IMU -> SideEncoder --+
                               +-> fuse [L, R, |L-R|, L*R] (+ force) -> classifier
    RIGHT IMU -> SideEncoder --+       (one shared encoder: the two MPU6050s
    FORCE     -> ForceBranch --+        are the same sensor type)

* `SideEncoder` is either a 1D CNN or a CNN followed by an LSTM.
* The fusion is symmetric in L and R, so the activity prediction does not
  depend on which leg wears which IMU; asymmetry is the job of the bilateral
  metrics, not of the activity classifier.
* `n_force` is a constructor argument (0, 1, 2, ...). The force branch exists
  in the architecture now but is trained with n_force=0, because no public
  dataset has a force sensor matching the RehabSense FSRs. It is exercised by
  a shape test only; it will be trained on real RehabSense recordings.

Inputs per IMU: the six orientation-invariant channels from
`app.sensing.features.invariant_channels` plus three channels relative to the
calibrated neutral pose (tilt, acceleration along and rotation about the
neutral vertical), standardised with statistics from the training fold only.
"""

from __future__ import annotations

import torch
from torch import nn


class SideEncoder(nn.Module):
    def __init__(self, in_ch: int = 9, width: int = 32, temporal: str = "cnn"):
        super().__init__()
        self.temporal = temporal
        self.conv = nn.Sequential(
            nn.Conv1d(in_ch, width, 5, padding=2), nn.BatchNorm1d(width), nn.ReLU(),
            nn.Conv1d(width, 2 * width, 5, padding=2), nn.BatchNorm1d(2 * width), nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(2 * width, 2 * width, 3, padding=1), nn.BatchNorm1d(2 * width), nn.ReLU(),
            nn.Dropout(0.2),
        )
        self.out_dim = 2 * width
        if temporal == "cnn_lstm":
            self.lstm = nn.LSTM(2 * width, 2 * width, batch_first=True)

    def forward(self, x):            # x: (B, C, T)
        h = self.conv(x)              # (B, F, T')
        if self.temporal == "cnn_lstm":
            _, (hn, _) = self.lstm(h.transpose(1, 2))
            return hn[-1]
        return h.mean(dim=2)


class ForceBranch(nn.Module):
    def __init__(self, n_force: int, out_dim: int = 16):
        super().__init__()
        self.net = nn.Sequential(nn.Conv1d(n_force, 16, 5, padding=2), nn.ReLU(),
                                 nn.AdaptiveAvgPool1d(1), nn.Flatten(), nn.Linear(16, out_dim),
                                 nn.ReLU())
        self.out_dim = out_dim

    def forward(self, f):
        return self.net(f)


class FusionNet(nn.Module):
    def __init__(self, n_classes: int, temporal: str = "cnn", bilateral: bool = True,
                 n_force: int = 0, width: int = 32):
        super().__init__()
        self.bilateral = bilateral
        self.encoder = SideEncoder(9, width, temporal)
        d = self.encoder.out_dim
        fused = 4 * d if bilateral else d
        self.force = ForceBranch(n_force) if n_force > 0 else None
        if self.force is not None:
            fused += self.force.out_dim
        self.head = nn.Sequential(nn.Linear(fused, 128), nn.ReLU(), nn.Dropout(0.3),
                                  nn.Linear(128, n_classes))

    def forward(self, left, right=None, force=None):
        hl = self.encoder(left)
        if self.bilateral:
            hr = self.encoder(right)
            z = torch.cat([hl, hr, (hl - hr).abs(), hl * hr], dim=1)
        else:
            z = hl
        if self.force is not None:
            z = torch.cat([z, self.force(force)], dim=1)
        return self.head(z)


def n_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
