"""Real Ouster data via the official Ouster SDK.

One code path handles all of:

* a live sensor (hostname such as ``os-122345.local`` or an IP address) - the SDK
  fetches metadata over the sensor HTTP API, points the sensor's UDP output at
  this machine, and batches packets into frames;
* a ``.pcap`` recording (with its ``.json`` metadata next to it);
* an ``.osf`` recording.
"""

from __future__ import annotations

import logging
import time
from typing import Iterator, Optional

import numpy as np

from ..frame import Frame, SensorMeta
from .base import FrameSource

log = logging.getLogger("ouster_demo.source")


class OusterSource(FrameSource):
    def __init__(
        self,
        url: str,
        fps_cap: float = 0.0,
        loop: bool = False,
        live: bool = True,
        open_kwargs: Optional[dict] = None,
    ):
        # Imported lazily so the simulator works even if the SDK failed to install.
        from ouster.sdk import open_source, core  # noqa: WPS433

        self._core = core
        self._url = url
        self._live = live
        self._loop = loop and not live
        self._period = 1.0 / fps_cap if (fps_cap and not live) else 0.0
        self._open_source = open_source
        self._open_kwargs = open_kwargs or {}

        log.info("Opening Ouster source %r (this can take a few seconds for a live sensor)", url)
        self._src = open_source(url, collate=False, **self._open_kwargs)
        self._info = self._src.sensor_info[0]
        self._lut = core.XYZLut(self._info)
        fmt = self._info.format
        self._meta = SensorMeta(
            model=str(self._info.prod_line or "Ouster"),
            serial=str(self._info.sn or ""),
            firmware=str(self._info.fw_rev or ""),
            lidar_mode=f"{fmt.columns_per_frame}x{fmt.fps}",
            rows=int(fmt.pixels_per_column),
            cols=int(fmt.columns_per_frame),
            source=url,
        )
        log.info("Connected: %s", self._meta.as_dict())

    @property
    def meta(self) -> SensorMeta:
        return self._meta

    def _reopen(self) -> None:
        try:
            self._src.close()
        except Exception:  # noqa: BLE001
            pass
        self._src = self._open_source(self._url, collate=False, **self._open_kwargs)

    def frames(self) -> Iterator[Frame]:
        core = self._core
        frame_id = 0
        next_t = time.monotonic()
        while True:
            produced = 0
            for frame_set in self._src:
                lf: Optional[object] = frame_set[0] if len(frame_set) else None
                if lf is None:
                    continue
                produced += 1
                rng = np.asarray(lf.field(core.ChanField.RANGE))
                xyz = np.asarray(self._lut(lf), dtype=np.float32)
                if lf.has_field(core.ChanField.REFLECTIVITY):
                    refl = np.clip(np.asarray(lf.field(core.ChanField.REFLECTIVITY)), 0, 255).astype(np.uint8)
                else:
                    refl = np.zeros(rng.shape, np.uint8)
                # RANGE is in millimetres (sensor native); convert to metres.
                range_m = (rng.astype(np.float32) * 0.001)
                frame_id += 1
                yield Frame(
                    xyz=xyz,
                    range_m=range_m,
                    reflectivity=refl,
                    timestamp=time.monotonic(),
                    frame_id=frame_id,
                    meta=self._meta,
                )
                if self._period:
                    next_t += self._period
                    delay = next_t - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        next_t = time.monotonic()
            if self._live or not self._loop or produced == 0:
                return
            log.info("End of recording - looping")
            self._reopen()

    def close(self) -> None:
        try:
            self._src.close()
        except Exception:  # noqa: BLE001
            pass
