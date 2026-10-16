from __future__ import annotations

from ..config import Settings
from .base import FrameSource


def open_frame_source(settings: Settings) -> FrameSource:
    """Create the right source for ``settings.source`` (sim | file | live sensor)."""
    kind = settings.source_kind
    if kind == "none":
        raise RuntimeError("no source configured")
    if kind == "sim":  # test fixture only
        from ..dev.sim_source import SimSource

        return SimSource(model="os0", fps=settings.fps)
    from .ouster_source import OusterSource

    return OusterSource(
        settings.source,
        fps_cap=settings.fps,
        loop=settings.loop,
        live=(kind == "sensor"),
        open_kwargs=settings.sensor_kwargs() if kind == "sensor" else {},
    )


__all__ = ["open_frame_source", "FrameSource"]
