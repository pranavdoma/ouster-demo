from fastapi.testclient import TestClient

from ouster_demo.config import Settings
from ouster_demo.protocol import decode_frame
from ouster_demo.server import create_app


def test_server_streams_frames():
    s = Settings(source="sim")
    with TestClient(create_app(s)) as client:
        assert client.get("/api/health").json()["ok"] is True
        assert client.get("/").status_code == 200
        assert client.get("/vendor/three.module.min.js").status_code == 200
        assert client.get("/assets/logo-full.png").status_code == 200
        with client.websocket_connect("/ws") as ws:
            got = None
            for _ in range(40):
                msg = ws.receive()
                if msg.get("bytes"):
                    got = msg["bytes"]
                    break
            assert got is not None
            header, xyz, _, _ = decode_frame(got)
            assert header["n"] > 10000 and header["sensor"]["rows"] == 128
        assert client.get("/api/params").json()["max_range_m"] > 0


def test_bad_source_reports_error_and_keeps_serving():
    s = Settings(source="203.0.113.1")  # TEST-NET, never reachable
    s.timeout = 1.0
    with TestClient(create_app(s)) as client:
        import time

        for _ in range(60):
            st = client.get("/api/status").json()
            if st["state"] == "error":
                break
            time.sleep(0.5)
        assert st["state"] == "error"
        assert st["message"]
        assert client.get("/api/health").json()["ok"] is True
