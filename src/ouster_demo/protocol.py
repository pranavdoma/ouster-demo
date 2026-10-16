"""Binary wire format for streaming frames to the browser.

Layout (little endian)::

    uint32  header_len            length of the JSON header in bytes (already padded to 4)
    bytes   header_json           UTF-8 JSON, space padded to a multiple of 4 bytes
    int16   xyz[3 * N]            centimetres, sensor frame
    uint8   reflectivity[N]
    uint8   tag[N]                see perception.pipeline TAG_*

N is ``header["n"]``. 8 bytes per point: ~0.6 MB for a full 128x1024 OS0 frame.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Dict

import numpy as np

from .perception.pipeline import PerceptionResult


def _track_json(tr) -> Dict[str, Any]:
    return {
        "id": tr.tid,
        "cls": tr.cls,
        "c": [round(float(tr.state[0]), 2), round(float(tr.state[1]), 2), round(float(tr.center_z), 2)],
        "s": [round(float(v), 2) for v in tr.size],
        "yaw": round(float(tr.yaw), 3),
        "v": [round(float(tr.state[2]), 2), round(float(tr.state[3]), 2)],
        "speed": round(tr.speed, 2),
        "moving": bool(tr.moving),
        "trail": [[round(x, 2), round(y, 2)] for x, y in list(tr.trail)[::2]],
    }


def encode_frame(res: PerceptionResult, header_extra: Dict[str, Any]) -> bytes:
    n = res.points.shape[0]
    header = {
        "type": "frame",
        "n": int(n),
        "frame_id": res.frame_id,
        "tracks": [_track_json(t) for t in res.tracks],
        "timings": {k: round(v, 2) for k, v in res.timings_ms.items()},
        "ground": res.ground,
        "clusters": res.n_clusters,
    }
    header.update(header_extra)
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    raw += b" " * ((-len(raw)) % 4)
    xyz_cm = np.clip(np.rint(res.points * 100.0), -32767, 32767).astype("<i2")
    return b"".join(
        (
            struct.pack("<I", len(raw)),
            raw,
            xyz_cm.tobytes(),
            res.reflectivity.astype(np.uint8).tobytes(),
            res.tags.astype(np.uint8).tobytes(),
        )
    )


def decode_frame(buf: bytes):
    """Inverse of :func:`encode_frame` (used by tests and offline tooling)."""
    (hlen,) = struct.unpack_from("<I", buf, 0)
    header = json.loads(buf[4 : 4 + hlen].decode("utf-8"))
    n = header["n"]
    off = 4 + hlen
    xyz = np.frombuffer(buf, dtype="<i2", count=3 * n, offset=off).reshape(n, 3) / 100.0
    off += 6 * n
    refl = np.frombuffer(buf, dtype=np.uint8, count=n, offset=off)
    off += n
    tags = np.frombuffer(buf, dtype=np.uint8, count=n, offset=off)
    return header, xyz, refl, tags
