"""Test-only Ouster-like simulator (NOT part of the product; used by the test-suite).

Not a toy point generator: it builds a genuine Ouster ``SensorInfo`` (128 beams
with real OS0 / OS1 / OS2 elevation spreads), ray-casts an urban scene through the
exact per-pixel beam directions, produces a *range image* in millimetres, and then
runs it through the Ouster SDK ``XYZLut`` - the same projection that real sensor
data goes through. If the pipeline works on the simulator it is exercising the
same code path as a live sensor, so this doubles as a regression harness.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Iterator, List

import numpy as np

from ..frame import Frame, SensorMeta
from ..sources.base import FrameSource

# model -> (product line, half vertical FOV in degrees, max range in metres, beam-origin offset mm)
MODELS = {
    "os0": ("OS-0-128", 45.0, 60.0, 27.67),
    "os1": ("OS-1-128", 22.5, 120.0, 15.806),
    "os2": ("OS-2-128", 11.25, 200.0, 13.762),
}

SENSOR_HEIGHT_M = 1.8  # sensor origin above ground


@dataclass
class Actor:
    uid: int
    cls: str
    pos: np.ndarray            # (x, y) centre on the ground plane, metres (sensor frame)
    yaw: float
    size: tuple                # (length, width, height)
    speed: float = 0.0         # m/s along yaw (straight movers)
    reflectivity: int = 80
    static: bool = False
    orbit: float = 0.0         # >0: drive CCW around the sensor at this radius; <0: CW (ring road)
    phi: float = 0.0           # orbit angle

    def step(self, dt: float) -> None:
        if self.static or self.speed == 0.0:
            return
        if self.orbit:
            r = abs(self.orbit)
            sign = 1.0 if self.orbit > 0 else -1.0
            self.phi += sign * self.speed / r * dt
            self.pos = np.array([r * np.cos(self.phi), r * np.sin(self.phi)])
            self.yaw = self.phi + sign * np.pi / 2
            return
        self.pos = self.pos + dt * self.speed * np.array([np.cos(self.yaw), np.sin(self.yaw)])
        rad = float(np.hypot(*self.pos))
        if rad > 8.0 or rad < 3.5:  # pedestrians stay on the inner plaza (and never walk through the sensor)
            self.yaw = (self.yaw + np.pi) % (2 * np.pi)
            self.pos = self.pos + dt * self.speed * np.array([np.cos(self.yaw), np.sin(self.yaw)]) * 2

    def velocity(self) -> tuple:
        return (float(self.speed * np.cos(self.yaw)), float(self.speed * np.sin(self.yaw)))

    def truth(self) -> dict:
        return {
            "id": self.uid,
            "cls": self.cls,
            "center": [float(self.pos[0]), float(self.pos[1]), float(-SENSOR_HEIGHT_M + self.size[2] / 2)],
            "size": [float(s) for s in self.size],
            "yaw": float(self.yaw),
            "velocity": list(self.velocity()) if not self.static else [0.0, 0.0],
        }


def _scene(rng: np.random.Generator) -> List[Actor]:
    """A plaza with a ring road: every vehicle is seen from all aspects as it circles the sensor."""
    a: List[Actor] = []
    uid = 0

    def add(*args, **kwargs):
        nonlocal uid
        uid += 1
        a.append(Actor(uid, *args, **kwargs))

    def orbiter(cls, radius, phi0, size, speed, refl):
        sign = 1.0 if radius > 0 else -1.0
        r = abs(radius)
        add(cls, np.array([r * np.cos(phi0), r * np.sin(phi0)]), phi0 + sign * np.pi / 2, size,
            speed=speed, reflectivity=refl, orbit=radius, phi=phi0)

    # Surrounding buildings (a 60 m square courtyard) - classified as "structure".
    add("building", np.array([0.0, 30.0]), 0.0, (62.0, 1.0, 9.0), reflectivity=45, static=True)
    add("building", np.array([0.0, -30.0]), 0.0, (62.0, 1.0, 9.0), reflectivity=40, static=True)
    add("building", np.array([30.0, 0.0]), np.pi / 2, (62.0, 1.0, 9.0), reflectivity=42, static=True)
    add("building", np.array([-30.0, 0.0]), np.pi / 2, (62.0, 1.0, 9.0), reflectivity=38, static=True)
    # Street lamps.
    for ang in np.deg2rad([20, 110, 200, 290]):
        add("pole", np.array([22.0 * np.cos(ang), 22.0 * np.sin(ang)]), 0.0, (0.3, 0.3, 5.5), reflectivity=200, static=True)
    # Parked cars on the outer kerb.
    add("car", np.array([23.0, -9.0]), 1.2, (4.5, 1.9, 1.5), reflectivity=110, static=True)
    add("car", np.array([-21.0, 11.0]), -0.4, (4.4, 1.9, 1.45), reflectivity=95, static=True)
    # Ring road traffic (CCW inner lane, CW outer lane).
    orbiter("car", 15.0, 0.3, (4.6, 1.9, 1.5), 7.5, 120)
    orbiter("car", 15.0, 3.5, (4.2, 1.8, 1.45), 6.5, 100)
    orbiter("car", -20.0, 1.6, (4.5, 1.9, 1.55), 8.5, 130)
    orbiter("truck", -20.0, 4.4, (8.5, 2.5, 3.3), 6.0, 90)
    orbiter("cyclist", 11.0, 5.0, (1.8, 0.6, 1.75), 4.2, 70)
    # Pedestrians on the plaza.
    add("pedestrian", np.array([5.0, -4.0]), np.pi / 2, (0.55, 0.5, 1.75), speed=1.3, reflectivity=60)
    add("pedestrian", np.array([-5.0, 6.0]), -np.pi / 4, (0.55, 0.5, 1.7), speed=1.1, reflectivity=55)
    add("pedestrian", np.array([-4.5, -3.8]), 0.3, (0.55, 0.5, 1.65), speed=1.4, reflectivity=65)
    add("pedestrian", np.array([-3.0, -5.5]), 0.3, (0.55, 0.5, 1.8), speed=1.4, reflectivity=60)
    return a


class SimSource(FrameSource):
    def __init__(self, model: str = "os0", fps: float = 10.0, columns: int = 1024, seed: int = 7, realtime: bool = True):
        model = model.lower()
        if model not in MODELS:
            raise ValueError(f"unknown sim model {model!r}; choose from {sorted(MODELS)}")
        self._model = model
        self._fps = fps
        self._realtime = realtime
        self._rng = np.random.default_rng(seed)
        self._max_range = MODELS[model][2]
        rows = 128
        self._shape = (rows, columns)
        self._origins, self._dirs = self._beam_rays()
        self.actors = _scene(self._rng)
        self._meta = SensorMeta(
            model=MODELS[model][0] + " (simulated)",
            serial="SIM0000001",
            firmware="sim",
            lidar_mode=f"{columns}x10",
            rows=rows,
            cols=columns,
            source="built-in simulator",
        )

    @property
    def meta(self) -> SensorMeta:
        return self._meta

    def _beam_rays(self):
        """Per-pixel ray origin/direction from analytic OS0/OS1/OS2 beam angles (128 rows)."""
        h, w = self._shape
        half_fov = MODELS[self._model][1]
        alt = np.deg2rad(np.linspace(half_fov, -half_fov, h))[:, None]
        az = np.deg2rad(-np.arange(w) * 360.0 / w)[None, :]     # Ouster scans clockwise
        d = np.stack([np.cos(alt) * np.cos(az), np.cos(alt) * np.sin(az), np.sin(alt) + 0 * az], axis=2)
        o = np.zeros_like(d)
        return o.reshape(-1, 3), d.reshape(-1, 3)

    def _cast(self):
        o, d = self._origins, self._dirs
        n = o.shape[0]
        t_best = np.full(n, np.inf)
        refl = np.zeros(n, np.float32)

        # ground plane z = -SENSOR_HEIGHT_M
        dz = d[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            tg = (-SENSOR_HEIGHT_M - o[:, 2]) / dz
        hit_g = (dz < -1e-6) & (tg > 0)
        t_best[hit_g] = tg[hit_g]
        refl[hit_g] = 28.0

        h, w = self._shape
        # Beams in one column share an azimuth, so cull per *column* (1024 values)
        # instead of per ray (131k values).
        mid = h // 2
        dxy_c = d.reshape(h, w, 3)[mid, :, :2]
        dxy_n = dxy_c / np.maximum(np.linalg.norm(dxy_c, axis=1, keepdims=True), 1e-9)
        o_c = o.reshape(h, w, 3)[mid, :, :2]
        row_base = (np.arange(h) * w)[:, None]

        for ac in self.actors:
            cx, cy = ac.pos
            zc = -SENSOR_HEIGHT_M + ac.size[2] / 2
            # Cheap horizontal cull: only rays passing near the actor's bounding circle
            # take part in the (more expensive) oriented-box test.
            radius = 0.5 * float(np.hypot(ac.size[0], ac.size[1])) + 0.2
            relc = np.array([cx, cy]) - o_c
            along = relc[:, 0] * dxy_n[:, 0] + relc[:, 1] * dxy_n[:, 1]
            perp = np.abs(relc[:, 0] * dxy_n[:, 1] - relc[:, 1] * dxy_n[:, 0])
            cols = np.nonzero((perp < radius) & (along > -radius))[0]
            if cols.size == 0:
                continue
            idx = (row_base + cols[None, :]).ravel()
            oi, di = o[idx], d[idx]
            c, s = np.cos(ac.yaw), np.sin(ac.yaw)
            half = np.array([ac.size[0], ac.size[1], ac.size[2]]) / 2
            rel = oi - np.array([cx, cy, zc])
            # world -> box frame (rotate by -yaw about z)
            ol = np.stack([c * rel[:, 0] + s * rel[:, 1], -s * rel[:, 0] + c * rel[:, 1], rel[:, 2]], axis=1)
            dl = np.stack([c * di[:, 0] + s * di[:, 1], -s * di[:, 0] + c * di[:, 1], di[:, 2]], axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                inv = 1.0 / dl
                t1 = (-half - ol) * inv
                t2 = (half - ol) * inv
            tmin = np.nanmax(np.minimum(t1, t2), axis=1)
            tmax = np.nanmin(np.maximum(t1, t2), axis=1)
            hit = (tmax >= tmin) & (tmin > 0.05)
            better = hit & (tmin < t_best[idx])
            sel = idx[better]
            t_best[sel] = tmin[better]
            refl[sel] = ac.reflectivity

        return t_best, refl

    def render(self, dt: float) -> Frame:
        for ac in self.actors:
            ac.step(dt)
        t, refl = self._cast()
        h, w = self._shape
        # range noise (σ = 1.5 cm), 1% dropouts, max range cutoff
        t = t + self._rng.normal(0.0, 0.015, t.shape)
        valid = np.isfinite(t) & (t > 0.3) & (t < self._max_range) & (self._rng.random(t.shape) > 0.01)
        range_mm = np.where(valid, np.round(t * 1000.0), 0).astype(np.uint32).reshape(h, w)
        xyz = (self._dirs.reshape(h, w, 3) * (range_mm[..., None] * 0.001)).astype(np.float32)
        refl_img = np.clip(refl + self._rng.normal(0, 4, refl.shape), 0, 255).astype(np.uint8).reshape(h, w)
        refl_img[range_mm == 0] = 0
        return Frame(
            xyz=xyz,
            range_m=(range_mm.astype(np.float32) * 0.001),
            reflectivity=refl_img,
            timestamp=time.monotonic(),
            meta=self._meta,
            truth=[a.truth() for a in self.actors if a.cls in {"car", "truck", "pedestrian", "cyclist"}],
        )

    def frames(self) -> Iterator[Frame]:
        dt = 1.0 / self._fps
        next_t = time.monotonic()
        frame_id = 0
        while True:
            fr = self.render(dt)
            frame_id += 1
            fr.frame_id = frame_id
            yield fr
            if self._realtime:
                next_t += dt
                delay = next_t - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_t = time.monotonic()
