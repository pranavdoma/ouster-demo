"""Background engine: source -> perception -> encoded frame, with auto-reconnect.

The engine owns a worker thread. The newest encoded frame is kept in memory and
every connected browser gets the *latest* frame (stale frames are dropped, so a
slow client never builds latency).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, Optional

from .config import Settings
from .perception import PerceptionPipeline
from .protocol import encode_frame
from .sources import open_frame_source

log = logging.getLogger("ouster_demo.engine")


class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.seq = 0
        self.latest: Optional[bytes] = None
        self.status: Dict[str, Any] = {"state": "starting", "message": "", "source": settings.source}
        self.stats: Dict[str, Any] = {"fps": 0.0, "frames": 0, "errors": 0}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._cond: Optional[asyncio.Condition] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._run_stop = threading.Event()
        self._lock = threading.Lock()

    # ---- lifecycle -------------------------------------------------------------------
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._cond = asyncio.Condition()
        self._spawn()

    def stop(self) -> None:
        self._stop.set()
        self._run_stop.set()

    def _spawn(self) -> None:
        with self._lock:
            self._run_stop.set()                 # ask any previous worker to exit
            self._run_stop = threading.Event()
            self._thread = threading.Thread(target=self._worker, args=(self._run_stop,), daemon=True, name="engine")
            self._thread.start()

    def set_source(self, source: str) -> None:
        """Switch source at runtime (type a sensor IP in the UI)."""
        self.settings.source = source.strip()
        self._spawn()

    # ---- status / publishing -----------------------------------------------------------
    def _set_status(self, state: str, message: str = "", meta: Optional[dict] = None) -> None:
        self.status = {
            "state": state,
            "message": message,
            "source": self.settings.source,
            "source_kind": self.settings.source_kind,
            "sensor": meta,
        }
        self._publish(None)

    def _publish(self, payload: Optional[bytes]) -> None:
        if payload is not None:
            self.latest = payload
        self.seq += 1
        if self._loop is not None and self._cond is not None:
            async def _notify() -> None:
                async with self._cond:  # type: ignore[union-attr]
                    self._cond.notify_all()  # type: ignore[union-attr]

            asyncio.run_coroutine_threadsafe(_notify(), self._loop)

    async def wait_for_update(self, last_seq: int, timeout: float = 5.0) -> int:
        assert self._cond is not None
        async with self._cond:
            try:
                await asyncio.wait_for(self._cond.wait_for(lambda: self.seq != last_seq), timeout)
            except asyncio.TimeoutError:
                pass
        return self.seq

    # ---- worker --------------------------------------------------------------------
    def _worker(self, stop: threading.Event) -> None:
        backoff = 2.0
        if not self.settings.source:
            self._set_status("idle", "Enter the sensor hostname or IP address to start streaming.")
            return
        while not stop.is_set() and not self._stop.is_set():
            src = None
            try:
                self._set_status("connecting", f"Opening {self.settings.source}...")
                src = open_frame_source(self.settings)
                if stop.is_set():
                    src.close()
                    return
                meta = src.meta.as_dict()
                self._set_status("streaming", "", meta)
                backoff = 2.0
                self._stream(src, stop, meta)
                if stop.is_set():
                    return
                raise RuntimeError("source ended")
            except Exception as exc:  # noqa: BLE001 - surfaced in the UI, then retry
                if stop.is_set():
                    return
                log.exception("source error")
                self.stats["errors"] += 1
                self._set_status("error", f"{type(exc).__name__}: {exc}")
                for _ in range(int(backoff * 10)):
                    if stop.is_set() or self._stop.is_set():
                        return
                    time.sleep(0.1)
                backoff = min(backoff * 1.7, 15.0)
            finally:
                if src is not None:
                    try:
                        src.close()
                    except Exception:  # noqa: BLE001
                        pass

    def _stream(self, src, stop: threading.Event, meta: dict) -> None:
        pipe = PerceptionPipeline(self.settings.perception)
        last_pub = time.monotonic()
        min_interval = 1.0 / max(self.settings.fps, 1.0) * 0.5   # UI cap: never faster than 2x nominal
        ema_fps = 0.0
        for frame in src.frames():
            if stop.is_set() or self._stop.is_set():
                return
            now = time.monotonic()
            if now - last_pub < min_interval:
                continue
            try:
                res = pipe.process(frame)
                payload = encode_frame(
                    res,
                    {
                        "t": time.time(),
                        "fps": round(ema_fps, 1),
                        "sensor": meta,
                        "latency_ms": round((time.monotonic() - frame.timestamp) * 1e3, 1),
                        "truth": frame.truth,
                    },
                )
            except Exception:  # noqa: BLE001 - one bad frame must not kill the stream
                log.exception("perception error on frame %s", frame.frame_id)
                self.stats["errors"] += 1
                continue
            dt = now - last_pub
            last_pub = now
            if dt > 0:
                ema_fps = 0.9 * ema_fps + 0.1 * (1.0 / dt) if ema_fps else 1.0 / dt
            self.stats.update(fps=round(ema_fps, 1), frames=self.stats["frames"] + 1)
            self._publish(payload)
