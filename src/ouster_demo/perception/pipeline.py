"""End-to-end perception pipeline: frame -> ground -> clusters -> boxes -> tracks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

from ..config import PerceptionParams
from ..frame import Frame
from .boxes import build_detections
from .cluster import cluster_points
from .ground import GroundEstimator
from .tracker import Tracker, Track

# per-point tags sent to the UI (kept in sync with web/app.js)
TAG_NONE, TAG_GROUND, TAG_STRUCTURE, TAG_VEHICLE, TAG_PED, TAG_CYCLIST, TAG_OTHER = range(7)

_CLASS_TAG = {
    "structure": TAG_STRUCTURE,
    "car": TAG_VEHICLE,
    "truck": TAG_VEHICLE,
    "pedestrian": TAG_PED,
    "cyclist": TAG_CYCLIST,
}


@dataclass
class PerceptionResult:
    frame_id: int
    points: np.ndarray                 # (N, 3) float32
    reflectivity: np.ndarray           # (N,) uint8
    tags: np.ndarray                   # (N,) uint8
    tracks: List[Track]
    timings_ms: Dict[str, float]
    ground: Dict[str, float]
    n_clusters: int = 0
    extra: dict = field(default_factory=dict)


class PerceptionPipeline:
    def __init__(self, params: PerceptionParams):
        self.params = params
        self.ground = GroundEstimator()
        self.tracker = Tracker()

    def process(self, frame: Frame) -> PerceptionResult:
        p = self.params
        timings: Dict[str, float] = {}
        t0 = time.perf_counter()

        # --- 1. flatten + range gate -------------------------------------------------
        valid = frame.range_m > p.min_range_m
        pts = frame.xyz[valid]
        refl = frame.reflectivity[valid]
        n = pts.shape[0]
        tags = np.zeros(n, dtype=np.uint8)
        rng_xy = np.hypot(pts[:, 0], pts[:, 1])
        in_range = rng_xy < p.max_range_m
        timings["prep"] = (time.perf_counter() - t0) * 1e3

        # --- 2. ground ---------------------------------------------------------------
        t1 = time.perf_counter()
        self.ground.fit(pts[in_range])
        if not self.ground.initialised and in_range.any():
            # No floor found yet (e.g. sensor staring at a wall): treat the lowest points as ground level
            self.ground.d = -float(np.percentile(pts[in_range][:, 2], 2.0))
        height = self.ground.height(pts)
        is_ground = in_range & (np.abs(height) <= p.ground_thresh_m)
        candidates = in_range & (height > p.ground_thresh_m) & (height < p.max_height_m)
        tags[is_ground] = TAG_GROUND
        timings["ground"] = (time.perf_counter() - t1) * 1e3

        # --- 3. clustering -----------------------------------------------------------
        t2 = time.perf_counter()
        cand_idx = np.flatnonzero(candidates)
        cpts = pts[cand_idx]
        labels = cluster_points(cpts, p.voxel_m, p.cluster_eps_m)
        timings["cluster"] = (time.perf_counter() - t2) * 1e3

        # --- 4. boxes + classification ----------------------------------------------
        t3 = time.perf_counter()
        dets = build_detections(cpts, labels, height[cand_idx], p.min_cluster_points, p.max_extent_m)
        timings["boxes"] = (time.perf_counter() - t3) * 1e3

        # --- 5. tracking -------------------------------------------------------------
        t4 = time.perf_counter()
        det_tracks = self.tracker.update(dets, frame.timestamp)
        timings["track"] = (time.perf_counter() - t4) * 1e3

        # paint per-point tags by (temporally smoothed) object class
        for det, tid in zip(dets, det_tracks):
            tr = self.tracker.tracks.get(tid)
            cls = tr.cls if tr is not None else det.cls
            tags[cand_idx[det.point_idx]] = _CLASS_TAG.get(cls, TAG_OTHER)
        leftover = candidates & (tags == TAG_NONE)
        tags[leftover] = TAG_OTHER  # clusters too small to be an object: show as generic obstacle

        timings["total"] = (time.perf_counter() - t0) * 1e3
        confirmed = [t for t in self.tracker.tracks.values() if t.confirmed and t.misses <= 2]
        return PerceptionResult(
            frame_id=frame.frame_id,
            points=pts,
            reflectivity=refl,
            tags=tags,
            tracks=confirmed,
            timings_ms=timings,
            ground={
                "nx": float(self.ground.normal[0]),
                "ny": float(self.ground.normal[1]),
                "nz": float(self.ground.normal[2]),
                "z": float(-self.ground.d / max(self.ground.normal[2], 1e-6)),
                "inlier_fraction": float(self.ground.last_inlier_fraction),
            },
            n_clusters=len(dets),
            extra={"detections": dets},
        )
