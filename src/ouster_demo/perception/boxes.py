"""Oriented 3D bounding boxes and rule-based classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np


@dataclass
class Detection:
    center: np.ndarray                 # (x, y, z) box centre, sensor frame
    size: np.ndarray                   # (length, width, height), length >= width
    yaw: float                         # radians, direction of the box's long axis
    cls: str                           # pedestrian | cyclist | car | truck | pole | structure | unknown
    n_points: int
    point_idx: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64), repr=False)
    distance: float = 0.0


_ANGLES = np.deg2rad(np.arange(0, 90, 4.0))
_C, _S = np.cos(_ANGLES), np.sin(_ANGLES)


def min_area_rect(xy: np.ndarray):
    """Minimum-area bounding rectangle by angle sweep.

    Returns (centre_xy, length, width, yaw) with length >= width and yaw the
    direction of the long side in [0, pi).
    """
    if xy.shape[0] > 1500:
        xy = xy[:: xy.shape[0] // 1500 + 1]
    # project onto each candidate axis pair
    u = xy[:, 0:1] * _C[None, :] + xy[:, 1:2] * _S[None, :]       # along angle
    v = -xy[:, 0:1] * _S[None, :] + xy[:, 1:2] * _C[None, :]      # perpendicular
    umin, umax = u.min(axis=0), u.max(axis=0)
    vmin, vmax = v.min(axis=0), v.max(axis=0)
    area = (umax - umin) * (vmax - vmin)
    k = int(np.argmin(area))
    cu, cv = 0.5 * (umin[k] + umax[k]), 0.5 * (vmin[k] + vmax[k])
    c, s = _C[k], _S[k]
    centre = np.array([c * cu - s * cv, s * cu + c * cv])
    du, dv = umax[k] - umin[k], vmax[k] - vmin[k]
    yaw = _ANGLES[k]
    if du >= dv:
        length, width = du, dv
    else:
        length, width, yaw = dv, du, yaw + np.pi / 2
    return centre, float(length), float(width), float(yaw % np.pi)


def classify(length: float, width: float, height: float, max_extent: float) -> str:
    if max(length, width) > max_extent or height > 6.5:
        return "structure"
    if height >= 2.8 and length < 0.6 and width < 0.6:
        return "pole"
    if length < 1.25 and width < 1.1 and 0.9 <= height <= 2.2:
        return "pedestrian"
    if 1.25 <= length < 2.5 and width < 1.1 and 1.0 <= height <= 2.2:
        return "cyclist"
    if 2.5 <= length <= 6.6 and 1.1 <= width <= 2.7 and 0.8 <= height <= 2.5:
        return "car"
    if 6.6 < length <= 14.0 and width >= 1.8 and height >= 2.0:
        return "truck"
    if length < 3.0 and width < 1.5 and height < 0.9:
        return "debris"
    if max(length, width) >= 3.0:     # big thing that is not a vehicle: wall, partition, shelving
        return "structure"
    return "unknown"


def build_detections(
    pts: np.ndarray,
    labels: np.ndarray,
    ground_height: np.ndarray,
    min_points: int,
    max_extent: float,
) -> List[Detection]:
    """Turn clustered non-ground points into classified oriented boxes."""
    dets: List[Detection] = []
    if pts.shape[0] == 0:
        return dets
    order = np.argsort(labels, kind="stable")
    sorted_labels = labels[order]
    bounds = np.flatnonzero(np.diff(sorted_labels)) + 1
    for grp in np.split(order, bounds):
        if grp.size < min_points:
            continue
        p = pts[grp]
        centre_xy, length, width, yaw = min_area_rect(p[:, :2])
        h = ground_height[grp]                       # height above the ground plane per point
        z_top = float(h.max())
        z_bot = float(h.min())
        if z_bot < 0.5:                              # standing on the ground (ground points were removed)
            z_bot = 0.0
        height = z_top - z_bot
        # z of the ground plane directly under this cluster, in the sensor frame
        ground_z = float((p[:, 2] - h).mean())
        cls = classify(max(length, 0.2), max(width, 0.2), height, max_extent)
        if width < 0.6 and 1.2 <= length <= 9.5 and cls in ("unknown", "pedestrian", "cyclist", "debris", "structure"):
            # Only one face of the object is visible (flat slab), so its depth is unobservable.
            # Fill it in from a class prior and push the box centre away from the sensor.
            prior_w = 0.7 if length < 2.5 else (1.9 if length <= 6.6 else 2.5)
            filled = classify(length, prior_w, height, max_extent)
            if filled in ("car", "truck", "cyclist"):
                normal = np.array([-np.sin(yaw), np.cos(yaw)])
                if normal @ centre_xy < 0:
                    normal = -normal
                centre_xy = centre_xy + normal * (prior_w - width) / 2.0
                width, cls = prior_w, filled
        centre = np.array([centre_xy[0], centre_xy[1], ground_z + z_bot + height / 2.0])
        size = np.array([max(length, 0.2), max(width, 0.2), max(height, 0.2)])
        dets.append(
            Detection(
                center=centre,
                size=size,
                yaw=yaw,
                cls=cls,
                n_points=int(grp.size),
                point_idx=grp,
                distance=float(np.hypot(centre[0], centre[1])),
            )
        )
    return dets
