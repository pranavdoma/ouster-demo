import numpy as np
import pytest

from ouster_demo.config import PerceptionParams
from ouster_demo.perception import PerceptionPipeline
from ouster_demo.perception.boxes import classify, min_area_rect
from ouster_demo.perception.cluster import cluster_points
from ouster_demo.protocol import decode_frame, encode_frame
from ouster_demo.dev.sim_source import SimSource


@pytest.fixture(scope="module")
def run():
    src = SimSource("os0", realtime=False)
    pipe = PerceptionPipeline(PerceptionParams())
    res = frame = None
    for _ in range(40):
        frame = src.render(0.1)
        res = pipe.process(frame)
    return frame, res, pipe


def test_sim_uses_real_ouster_geometry():
    src = SimSource("os2", realtime=False)
    f = src.render(0.1)
    assert f.xyz.shape == (128, 1024, 3)
    assert f.valid.sum() > 20000
    assert "OS-2-128" in f.meta.model


def test_ground_plane_recovered(run):
    _, res, _ = run
    assert abs(res.ground["z"] - (-1.8)) < 0.05
    assert res.ground["nz"] > 0.999


def test_moving_objects_detected_with_speed(run):
    frame, res, _ = run
    moving_truth = [g for g in frame.truth if np.hypot(*g["velocity"]) > 0.5 and np.hypot(*g["center"][:2]) < 35]
    hits = 0
    for g in moving_truth:
        cands = [t for t in res.tracks if np.hypot(t.state[0] - g["center"][0], t.state[1] - g["center"][1]) < 2.0]
        if cands:
            hits += 1
    assert hits / len(moving_truth) >= 0.7


def test_vehicle_classes_present(run):
    _, res, _ = run
    classes = {t.cls for t in res.tracks}
    assert {"car", "pedestrian"} <= classes


def test_pipeline_fast_enough(run):
    _, res, _ = run
    assert res.timings_ms["total"] < 100  # must keep up with a 10 Hz sensor


def test_protocol_roundtrip(run):
    _, res, _ = run
    buf = encode_frame(res, {"fps": 9.9})
    header, xyz, refl, tags = decode_frame(buf)
    assert header["n"] == res.points.shape[0] == xyz.shape[0] == refl.shape[0] == tags.shape[0]
    assert np.abs(xyz - res.points).max() < 0.011  # centimetre quantisation
    assert len(header["tracks"]) == len(res.tracks)


def test_cluster_separates_blobs():
    rng = np.random.default_rng(0)
    a = rng.normal([0, 0, 0], 0.15, (200, 3))
    b = rng.normal([10, 0, 0], 0.15, (200, 3))
    labels = cluster_points(np.vstack([a, b]), 0.2, 0.55)
    assert len(set(labels[:200])) == 1 and len(set(labels[200:])) == 1
    assert labels[0] != labels[-1]


def test_min_area_rect_recovers_orientation():
    rng = np.random.default_rng(1)
    pts = rng.uniform([-2.0, -0.9], [2.0, 0.9], (800, 2))
    th = np.deg2rad(30)
    rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    c, length, width, yaw = min_area_rect(pts @ rot.T + [5, 3])
    assert abs(length - 4.0) < 0.3 and abs(width - 1.8) < 0.3
    assert abs(np.rad2deg(yaw) - 30) < 6
    assert np.allclose(c, [5, 3], atol=0.3)


def test_classify_rules():
    assert classify(4.5, 1.9, 1.5, 14) == "car"
    assert classify(0.6, 0.5, 1.7, 14) == "pedestrian"
    assert classify(8.5, 2.5, 3.3, 14) == "truck"
    assert classify(30, 1, 4, 14) == "structure"
