"""Euclidean clustering of non-ground points via voxel connectivity."""

from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree


def cluster_points(pts: np.ndarray, voxel: float, eps: float) -> np.ndarray:
    """Return a cluster label for every point (labels are 0..K-1).

    Points are first snapped to a voxel grid (fast, bounds the problem size no matter
    how dense the lidar is up close); voxel centres closer than ``eps`` are joined
    into connected components.
    """
    n = pts.shape[0]
    if n == 0:
        return np.empty(0, dtype=np.int64)
    grid = np.floor(pts / voxel).astype(np.int64)
    grid -= grid.min(axis=0)
    dims = grid.max(axis=0) + 1
    keys = (grid[:, 0] * dims[1] + grid[:, 1]) * dims[2] + grid[:, 2]
    uniq, first_idx, inverse = np.unique(keys, return_index=True, return_inverse=True)
    centres = (grid[first_idx] + 0.5) * voxel
    if centres.shape[0] == 1:
        return np.zeros(n, dtype=np.int64)

    tree = cKDTree(centres)
    pairs = tree.query_pairs(r=eps, output_type="ndarray")
    m = centres.shape[0]
    if pairs.shape[0] == 0:
        return inverse.astype(np.int64)
    graph = coo_matrix((np.ones(pairs.shape[0], dtype=np.int8), (pairs[:, 0], pairs[:, 1])), shape=(m, m))
    _, comp = connected_components(graph, directed=False)
    return comp[inverse].astype(np.int64)
