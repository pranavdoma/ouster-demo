"""Runtime configuration.

Everything is overridable with environment variables (see ``.env.example``) or
CLI flags, so the same container image can be pointed at any sensor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class PerceptionParams:
    """Tunable perception parameters (live-adjustable from the UI)."""

    min_range_m: float = 0.5          # drop returns closer than this (self-hits)
    max_range_m: float = 40.0         # perception range limit
    max_height_m: float = 2.6         # ignore points this far above the floor (ceiling, lights)
    ground_thresh_m: float = 0.18     # distance to ground plane that still counts as ground
    voxel_m: float = 0.20             # clustering voxel size
    cluster_eps_m: float = 0.55       # voxel-center connectivity radius
    min_cluster_points: int = 25      # minimum raw points for an object
    max_extent_m: float = 14.0        # clusters bigger than this are "structure" (walls, buildings)

    def update(self, values: dict) -> None:
        for key, val in values.items():
            if hasattr(self, key):
                setattr(self, key, type(getattr(self, key))(val))

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Settings:
    source: str = field(default_factory=lambda: _env("OUSTER_SOURCE", ""))
    """Sensor hostname / IP (e.g. 192.168.1.50 or os-122xxxx.local). Empty = wait for it to be entered in the UI.
    A .pcap/.osf path also works (same SDK code path) and 'sim' is a test-only fixture."""

    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8080")))
    fps: float = field(default_factory=lambda: float(_env("OUSTER_FPS", "10")))
    """Frame rate cap (sim pacing, pcap replay pacing, and UI streaming cap)."""

    loop: bool = field(default_factory=lambda: _env("OUSTER_LOOP", "1") == "1")
    """Loop pcap/OSF files when they end."""

    lidar_port: int = field(default_factory=lambda: int(_env("OUSTER_LIDAR_PORT", "0")))
    imu_port: int = field(default_factory=lambda: int(_env("OUSTER_IMU_PORT", "0")))
    """UDP destination ports for a live sensor (0 = SDK default / auto)."""

    no_auto_udp_dest: bool = field(default_factory=lambda: _env("OUSTER_NO_AUTO_UDP_DEST", "0") == "1")
    """Do not let the SDK point the sensor's UDP output at this machine (you configured it yourself)."""

    no_reinitialize: bool = field(default_factory=lambda: _env("OUSTER_NO_REINIT", "0") == "1")
    """Do not reinitialize the sensor even if its config disagrees."""

    soft_id_check: bool = field(default_factory=lambda: _env("OUSTER_SOFT_ID_CHECK", "0") == "1")
    """Keep parsing packets even if the sensor init_id / serial do not match the metadata."""

    timeout: float = field(default_factory=lambda: float(_env("OUSTER_TIMEOUT", "5")))
    """Seconds to wait for lidar packets before the stream is considered dead."""

    perception: PerceptionParams = field(default_factory=PerceptionParams)

    def sensor_kwargs(self) -> dict:
        """Extra keyword arguments for ``ouster.sdk.open_source`` (live sensors only)."""
        kw: dict = {"timeout": self.timeout}
        if self.lidar_port:
            kw["lidar_port"] = self.lidar_port
        if self.imu_port:
            kw["imu_port"] = self.imu_port
        if self.no_auto_udp_dest:
            kw["no_auto_udp_dest"] = True
        if self.no_reinitialize:
            kw["do_not_reinitialize"] = True
        if self.soft_id_check:
            kw["soft_id_check"] = True
        return kw

    @property
    def source_kind(self) -> str:
        if not self.source:
            return "none"
        if self.source.lower() == "sim":  # test fixture only (ouster_demo.dev)
            return "sim"
        if os.path.exists(os.path.expanduser(self.source)) or self.source.lower().endswith(
            (".pcap", ".osf", ".bag", ".mcap")
        ):
            return "file"
        return "sensor"
