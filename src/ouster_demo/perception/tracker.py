"""Multi-object tracker: constant-velocity Kalman filter + Hungarian association.

Velocities are expressed in the sensor frame. For a static sensor (tripod, roadside
unit, lab bench) that is the world frame; on a moving platform they are relative
velocities unless ego-motion is compensated upstream.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

from .boxes import Detection

CONFIRM_HITS = 3
MAX_MISSES = 6
GATE_M = 3.0
MOVING_SPEED_MS = 0.6
STATIC_CLASSES = {"structure", "pole"}


@dataclass
class Track:
    tid: int
    state: np.ndarray                  # [x, y, vx, vy]
    cov: np.ndarray
    center_z: float
    size: np.ndarray
    yaw: float
    cls: str
    hits: int = 1
    misses: int = 0
    age: int = 1
    votes: Counter = field(default_factory=Counter)
    trail: Deque[Tuple[float, float]] = field(default_factory=lambda: deque(maxlen=40))

    @property
    def confirmed(self) -> bool:
        return self.hits >= CONFIRM_HITS

    @property
    def speed(self) -> float:
        return float(np.hypot(self.state[2], self.state[3]))

    @property
    def moving(self) -> bool:
        return self.speed > MOVING_SPEED_MS


class Tracker:
    def __init__(self) -> None:
        self.tracks: Dict[int, Track] = {}
        self._next_id = 1
        self._last_t: float | None = None

    @staticmethod
    def _predict(tr: Track, dt: float) -> None:
        f = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
        q = 1.5  # process noise (m/s^2): responsive enough for cars cornering
        g = np.array([[0.5 * dt * dt, 0], [0, 0.5 * dt * dt], [dt, 0], [0, dt]])
        tr.state = f @ tr.state
        tr.cov = f @ tr.cov @ f.T + (g @ g.T) * q * q

    @staticmethod
    def _update(tr: Track, z: np.ndarray, r: float = 0.3) -> None:
        h = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        s = h @ tr.cov @ h.T + np.eye(2) * r * r
        k = tr.cov @ h.T @ np.linalg.inv(s)
        tr.state = tr.state + k @ (z - h @ tr.state)
        tr.cov = (np.eye(4) - k @ h) @ tr.cov

    def update(self, dets: List[Detection], t: float) -> List[int]:
        """Associate detections to tracks. Returns the track id per detection (-1 = none)."""
        dt = 0.1 if self._last_t is None else float(np.clip(t - self._last_t, 0.01, 0.5))
        self._last_t = t
        for tr in self.tracks.values():
            self._predict(tr, dt)

        ids = list(self.tracks.keys())
        det_to_track = [-1] * len(dets)
        matched_tracks = set()
        if ids and dets:
            cost = np.zeros((len(ids), len(dets)))
            for i, tid in enumerate(ids):
                px, py = self.tracks[tid].state[:2]
                for j, d in enumerate(dets):
                    cost[i, j] = np.hypot(px - d.center[0], py - d.center[1])
            rows, cols = linear_sum_assignment(cost)
            for r, c in zip(rows, cols):
                if cost[r, c] <= GATE_M:
                    det_to_track[c] = ids[r]
                    matched_tracks.add(ids[r])

        for j, d in enumerate(dets):
            tid = det_to_track[j]
            if tid == -1:
                st = np.array([d.center[0], d.center[1], 0.0, 0.0])
                cov = np.diag([0.3, 0.3, 4.0, 4.0])
                tr = Track(self._next_id, st, cov, float(d.center[2]), d.size.copy(), d.yaw, d.cls)
                tr.votes[d.cls] += 1
                tr.trail.append((float(st[0]), float(st[1])))
                self.tracks[self._next_id] = tr
                det_to_track[j] = self._next_id
                self._next_id += 1
                continue
            tr = self.tracks[tid]
            self._update(tr, d.center[:2])
            tr.hits += 1
            tr.misses = 0
            tr.age += 1
            a = 0.3
            tr.size = (1 - a) * tr.size + a * d.size
            tr.center_z = (1 - a) * tr.center_z + a * float(d.center[2])
            tr.votes[d.cls] += 1
            for k in list(tr.votes):  # decay so a class can still change
                tr.votes[k] *= 0.97
            tr.cls = tr.votes.most_common(1)[0][0]
            if tr.cls in STATIC_CLASSES:  # centroid of a wall/pole shifts with occlusion: not motion
                tr.state[2:] = 0.0
            # heading: velocity direction when moving, else smoothed box orientation (mod pi)
            if tr.speed > 1.5:
                tr.yaw = float(np.arctan2(tr.state[3], tr.state[2]))
            else:
                a2 = 0.25
                cur, new = np.array([np.cos(2 * tr.yaw), np.sin(2 * tr.yaw)]), np.array([np.cos(2 * d.yaw), np.sin(2 * d.yaw)])
                m = (1 - a2) * cur + a2 * new
                tr.yaw = float(0.5 * np.arctan2(m[1], m[0]))
            tr.trail.append((float(tr.state[0]), float(tr.state[1])))

        for tid in ids:
            if tid not in matched_tracks:
                tr = self.tracks[tid]
                tr.misses += 1
                tr.age += 1
        for tid in [k for k, v in self.tracks.items() if v.misses > MAX_MISSES]:
            del self.tracks[tid]
        return det_to_track
