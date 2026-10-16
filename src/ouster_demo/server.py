"""FastAPI app: static UI + WebSocket point-cloud stream + small control API."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .config import Settings
from .engine import Engine

log = logging.getLogger("ouster_demo.server")
WEB_DIR = Path(__file__).parent / "web"


class SourceRequest(BaseModel):
    source: str


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings()
    engine = Engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine.start(asyncio.get_running_loop())
        yield
        engine.stop()

    app = FastAPI(title="General Autonomy x Ouster demo", version=__version__, lifespan=lifespan)
    app.state.engine = engine

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "state": engine.status.get("state")}

    @app.get("/api/status")
    def status():
        return {**engine.status, "stats": engine.stats, "version": __version__}

    @app.get("/api/params")
    def get_params():
        return settings.perception.as_dict()

    @app.post("/api/params")
    def set_params(values: dict):
        settings.perception.update(values)
        return settings.perception.as_dict()

    @app.post("/api/source")
    def set_source(req: SourceRequest):
        engine.set_source(req.source)
        return JSONResponse({"ok": True, "source": settings.source})

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        last = -1
        last_status = ""

        async def push_status(force: bool = False) -> None:
            nonlocal last_status
            msg = json.dumps({"type": "status", **engine.status, "stats": engine.stats})
            if force or msg != last_status:
                last_status = msg
                await sock.send_text(msg)

        try:
            while True:
                seq = await engine.wait_for_update(last)
                if seq == last:          # idle tick (no new frame for a while): refresh status
                    await push_status(force=True)
                    continue
                last = seq
                await push_status()
                if engine.status.get("state") == "streaming" and engine.latest is not None:
                    await sock.send_bytes(engine.latest)
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
    return app
