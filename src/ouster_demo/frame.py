"""Source-agnostic lidar frame.

Every source (live sensor, pcap/OSF replay, simulator) yields ``Frame`` objects,
so the perception stack and the UI never need to know where data came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class SensorMeta:
    model: str = "unknown"            # e.g. OS-0-128
    serial: str = ""
    firmware: str = ""
    lidar_mode: str = ""              # e.g. 1024x10
    rows: int = 0                     # beams
    cols: int = 0                     # columns per frame
    source: str = ""                  # human readable origin

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Frame:
    xyz: np.ndarray                   # (H, W, 3) float32, metres, sensor frame (x fwd, y left, z up)
    range_m: np.ndarray               # (H, W) float32, 0 = no return
    reflectivity: np.ndarray          # (H, W) uint8
    timestamp: float                  # seconds (host monotonic or sensor time)
    frame_id: int = 0
    meta: Optional[SensorMeta] = None
    truth: list = field(default_factory=list)  # simulator ground-truth objects (empty for real data)

    @property
    def valid(self) -> np.ndarray:
        return self.range_m > 0.0
