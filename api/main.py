"""Stabilization Navigator API: FastAPI app that runs the agent and drives the A2UI surfaces.

Run (repo root):
    pip install -r api/requirements.txt -r agent/requirements.txt
    uvicorn api.main:app --reload --port 8080
    A4I_AGENT_MODE=mock uvicorn api.main:app --port 8080     # no GCP: replays the INT-1142 demo

Endpoints (full reference: docs/UI_API.md)
    GET  /health
    GET  /api/config
    GET  /api/a2ui/catalog                     navigator A2UI catalog definition (v1.0)
    POST /api/sessions                          -> {session_id}
    GET  /api/sessions/{sid}                    workspace state (queue + open case)
    GET  /api/sessions/{sid}/a2ui               createSurface snapshot of every surface
    POST /api/sessions/{sid}/messages           chat turn, streamed as SSE
    POST /api/sessions/{sid}/actions            A2UI v1.0 action envelope, streamed as SSE
    GET  /api/sessions/{sid}/cases              intake queue
    GET  /api/sessions/{sid}/cases/{cid}        one case (brief, memo, transcript)
    GET  /api/sessions/{sid}/cases/{cid}/brief  Stabilization Brief JSON
    GET  /api/sessions/{sid}/cases/{cid}/memo.md  intake memo download
    WS   /ws                                     the same, bidirectional (preferred by the UI)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .a2ui import surfaces as S
from .runners import make_runner
from .workspace import Workspace

log = logging.getLogger("navigator.api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

ROOT = Path(__file__).resolve().parents[1]
UI_DIST = Path(os.getenv("A4I_UI_DIST", ROOT / "ui" / "dist"))
CATALOG_FILE = Path(__file__).parent / "a2ui" / "navigator_catalog.json"

app = FastAPI(title="Tenant Stabilization Navigator API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("A4I_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_methods=["*"], allow_headers=["*"],
)

RUNNER = make_runner()
WORKSPACES: dict[str, Workspace] = {}


def workspace(session_id: str, create: bool = True) -> Workspace:
    ws = WORKSPACES.get(session_id)
    if ws is None:
        if not create:
            raise HTTPException(404, f"Unknown session {session_id}")
        ws = WORKSPACES[session_id] = Workspace(session_id, RUNNER)
    return ws


# ------------------------------------------------------------------------- REST


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent_mode": RUNNER.mode, "sessions": len(WORKSPACES)}


@app.get("/api/config")
def config() -> dict:
    return {
        "agent_mode": RUNNER.mode,
        "metro": "San Francisco",
        "a2ui": {"version": S.A2UI_VERSION, "catalogId": S.NAVIGATOR_CATALOG_ID,
                 "basicCatalogId": S.BASIC_CATALOG_ID, "surfaces": list(S.SURFACES)},
        "transports": {"websocket": "/ws", "sse": "/api/sessions/{session_id}/messages"},
    }


@app.get("/api/a2ui/catalog")
def a2ui_catalog() -> JSONResponse:
    return JSONResponse(json.loads(CATALOG_FILE.read_text()))


class NewSession(BaseModel):
    session_id: str | None = None


@app.post("/api/sessions")
def create_session(body: NewSession | None = None) -> dict:
    sid = (body.session_id if body else None) or uuid.uuid4().hex[:12]
    ws = workspace(sid)
    return {"session_id": sid, "active_case": ws.active_id, "agent_mode": RUNNER.mode}


@app.get("/api/sessions/{sid}")
def get_session(sid: str) -> dict:
    ws = workspace(sid, create=False)
    return {"session_id": sid, "active_case": ws.active_id,
            "cases": [c.case_id for c in ws.cases.values()], "case": ws.case.to_json()}


@app.get("/api/sessions/{sid}/a2ui")
def get_surfaces(sid: str) -> dict:
    """Every surface as createSurface messages: render this to restore the whole screen."""
    return {"messages": workspace(sid, create=False).snapshot()}


@app.get("/api/sessions/{sid}/cases")
def list_cases(sid: str) -> dict:
    ws = workspace(sid, create=False)
    from .a2ui.view import queue_model
    return queue_model(ws.cases, ws.active_id)


@app.get("/api/sessions/{sid}/cases/{cid}")
def get_case(sid: str, cid: str) -> dict:
    ws = workspace(sid, create=False)
    if cid not in ws.cases:
        raise HTTPException(404, f"Unknown case {cid}")
    return ws.cases[cid].to_json()


@app.get("/api/sessions/{sid}/cases/{cid}/brief")
def get_brief(sid: str, cid: str) -> dict:
    case = get_case(sid, cid)
    if not case["brief"]:
        raise HTTPException(404, "No brief yet for this case")
    return case["brief"]


@app.get("/api/sessions/{sid}/cases/{cid}/memo.md")
def get_memo(sid: str, cid: str) -> PlainTextResponse:
    case = get_case(sid, cid)
    if not case["memo"]["markdown"]:
        raise HTTPException(404, "No memo yet for this case")
    return PlainTextResponse(
        case["memo"]["markdown"], media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{cid}-intake-memo.md"'})


class ChatIn(BaseModel):
    text: str


def sse(events: AsyncIterator[dict]) -> StreamingResponse:
    async def gen():
        async for e in events:
            yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/sessions/{sid}/messages")
async def post_message(sid: str, body: ChatIn) -> StreamingResponse:
    return sse(workspace(sid).user_message(body.text))


@app.post("/api/sessions/{sid}/actions")
async def post_action(sid: str, body: dict[str, Any]) -> StreamingResponse:
    """Body: an A2UI v1.0 renderer-to-agent message, e.g. {"version": "1.0", "action": {...}}."""
    action = body.get("action") if "action" in body else body
    if not isinstance(action, dict) or "name" not in action:
        raise HTTPException(422, "Expected an A2UI v1.0 action message: {'version': '1.0', 'action': {...}}")
    return sse(workspace(sid).action(action))


# ------------------------------------------------------------------------- WebSocket


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """Client frames:
        {"type": "hello", "session_id"}                       -> snapshot of every surface + transcript
        {"type": "user_message", "session_id", "text"}        -> agent turn
        {"type": "a2ui_action", "session_id", "message": {"version": "1.0", "action": {...}}}
        {"type": "a2ui_error", "session_id", "message": {"version": "1.0", "error": {...}}}   (logged)
    """
    await ws.accept()
    try:
        while True:
            frame = await ws.receive_json()
            sid = str(frame.get("session_id") or "default")
            space = workspace(sid)
            kind = frame.get("type")
            if kind == "hello":
                for e in await space.connect():
                    await ws.send_json(e)
            elif kind == "user_message":
                async for e in space.user_message(str(frame.get("text", ""))):
                    await ws.send_json(e)
            elif kind == "a2ui_action":
                msg = frame.get("message") or {}
                action = msg.get("action") if isinstance(msg, dict) else None
                if not action:
                    await ws.send_json({"type": "error", "text": "a2ui_action needs message.action"})
                    continue
                async for e in space.action(action):
                    await ws.send_json(e)
            elif kind == "a2ui_error":
                log.warning("renderer error: %s", frame.get("message"))
            else:
                await ws.send_json({"type": "error", "text": f"Unknown frame type {kind!r}"})
    except WebSocketDisconnect:
        return


# ------------------------------------------------------------------------- static UI

if (UI_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        f = UI_DIST / path
        return FileResponse(f if path and f.is_file() else UI_DIST / "index.html")
