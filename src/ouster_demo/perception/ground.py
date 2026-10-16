"""Ground-plane estimation (RANSAC + least-squares refinement + temporal smoothing).

Works for a roof-mounted sensor, a tripod, or a sensor on a cart: all we assume is
that the lowest large, near-horizontal surface in view is the ground / floor.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


class GroundEstimator:
    def __init__(self, iterations: int = 80, inlier_m: float = 0.10, seed: int = 0):
        self.iterations = iterations
        self.inlier_m = inlier_m
        self._rng = np.random.default_rng(seed)
        self.normal = np.array([0.0, 0.0, 1.0])
        self.d = 1.8          # plane: n . p + d = 0  (so height = n . p + d)
        self.initialised = False
        self.last_inlier_fraction = 0.0

    def height(self, pts: np.ndarray) -> np.ndarray:
        """Signed height above the ground plane (m)."""
        return pts @ self.normal + self.d

    @staticmethod
    def _plane_from(p: np.ndarray) -> Optional[Tuple[np.ndarray, float]]:
        n = np.cross(p[1] - p[0], p[2] - p[0])
        norm = np.linalg.norm(n)
        if norm < 1e-6:
            return None
        n = n / norm
        if n[2] < 0:
            n = -n
        return n, -float(n @ p[0])

    def fit(self, pts: np.ndarray) -> None:
        """Update the ground plane from this frame's points (sensor frame, z up)."""
        if pts.shape[0] < 200:
            return
        rng_xy = np.hypot(pts[:, 0], pts[:, 1])
        near = pts[(rng_xy > 1.5) & (rng_xy < 30.0)]
        if near.shape[0] < 200:
            return
        # Candidate ground points: the lowest slab of the scene.
        z_low = np.percentile(near[:, 2], 2.0)
        cand = near[near[:, 2] < z_low + 0.6]
        if cand.shape[0] < 150:
            return
        if cand.shape[0] > 6000:
            cand = cand[self._rng.choice(cand.shape[0], 6000, replace=False)]

        best_n, best_d, best_cnt = None, 0.0, 0
        for _ in range(self.iterations):
            sample = cand[self._rng.choice(cand.shape[0], 3, replace=False)]
            plane = self._plane_from(sample)
            if plane is None:
                continue
            n, d = plane
            if n[2] < 0.92:  # ground must be near-horizontal (< ~23 deg tilt)
                continue
            cnt = int(np.count_nonzero(np.abs(cand @ n + d) < self.inlier_m))
            if cnt > best_cnt:
                best_n, best_d, best_cnt = n, d, cnt
        if best_n is None or best_cnt < 100:
            return

        # Least-squares refinement on inliers.
        inl = cand[np.abs(cand @ best_n + best_d) < self.inlier_m * 1.5]
        centroid = inl.mean(axis=0)
        _, _, vt = np.linalg.svd(inl - centroid, full_matrices=False)
        n = vt[2]
        if n[2] < 0:
            n = -n
        d = -float(n @ centroid)
        self.last_inlier_fraction = best_cnt / cand.shape[0]

        if not self.initialised:
            self.normal, self.d, self.initialised = n, d, True
        else:  # temporal smoothing keeps boxes from "breathing" frame to frame
            a = 0.2
            self.normal = (1 - a) * self.normal + a * n
            self.normal /= np.linalg.norm(self.normal)
            self.d = (1 - a) * self.d + a * d
