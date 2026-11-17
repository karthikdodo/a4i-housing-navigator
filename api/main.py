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
    POST /api/sessions/{sid}/uploads            tenant photo or audio clip (multipart `file`)
    GET  /api/uploads/{upload_id}               the stored file
    POST /api/sessions/{sid}/transcribe         voice clip -> transcript (Gemini, or the browser's live transcript)
    POST /api/sessions/{sid}/intake/voice       transcript -> New intake form fields (+ A2UI updates)
    WS   /ws                                     the same, bidirectional (preferred by the UI)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import media
from .a2ui import surfaces as S
from .runners import make_runner
from .workspace import Workspace

log = logging.getLogger("navigator.api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

ROOT = Path(__file__).resolve().parents[1]
UI_DIST = Path(os.getenv("A4I_UI_DIST", ROOT / "ui" / "dist"))
CATALOG_FILE = Path(__file__).parent / "a2ui" / "navigator_catalog.json"

app = FastAPI(title="Tenant Voice API", version="0.2.0")
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
        "voice": {"transcription": "gemini" if media.use_gemini(RUNNER.mode) else "browser",
                  "max_audio_mb": media.MAX_BYTES["audio"] // (1024 * 1024)},
        "uploads": {"image_types": sorted(media.IMAGE_TYPES), "max_image_mb": media.MAX_BYTES["image"] // (1024 * 1024)},
        "maps": {"has_api_key": bool(os.getenv("GOOGLE_MAPS_API_KEY"))},
    }


@app.get("/api/a2ui/catalog")
def a2ui_catalog() -> JSONResponse:
    return JSONResponse(json.loads(CATALOG_FILE.read_text()))


class NewSession(BaseModel):
    session_id: Optional[str] = None


@app.post("/api/sessions")
def create_session(body: Optional[NewSession] = None) -> dict:
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
    # Export is never blocked: an unreviewed memo downloads/copies with a DRAFT line on top.
    reviewed = case["memo"]["status"] == "reviewed"
    from .a2ui.view import DRAFT_STAMP
    text = case["memo"]["markdown"] if reviewed else DRAFT_STAMP + case["memo"]["markdown"]
    name = f"{cid}-intake-memo.md" if reviewed else f"{cid}-intake-memo-DRAFT.md"
    return PlainTextResponse(text, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


class ChatIn(BaseModel):
    text: str = ""
    attachments: List[str] = []
    voice: Optional[dict] = None


def sse(events: AsyncIterator[dict]) -> StreamingResponse:
    async def gen():
        async for e in events:
            yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/sessions/{sid}/messages")
async def post_message(sid: str, body: ChatIn) -> StreamingResponse:
    return sse(workspace(sid).user_message(body.text, attachments=body.attachments, voice=body.voice))


@app.post("/api/sessions/{sid}/actions")
async def post_action(sid: str, body: Dict[str, Any]) -> StreamingResponse:
    """Body: an A2UI v1.0 renderer-to-agent message, e.g. {"version": "1.0", "action": {...}}."""
    action = body.get("action") if "action" in body else body
    if not isinstance(action, dict) or "name" not in action:
        raise HTTPException(422, "Expected an A2UI v1.0 action message: {'version': '1.0', 'action': {...}}")
    return sse(workspace(sid).action(action))


# ------------------------------------------------------------------------- uploads, voice


async def _read_upload(file: UploadFile) -> media.Upload:
    data = await file.read(media.MAX_BYTES["audio"] + 1)
    try:
        return media.save_upload(data, file.content_type or "", file.filename or "")
    except media.UploadError as e:
        raise HTTPException(415 if "type" in str(e) else 413, str(e)) from e


@app.post("/api/sessions/{sid}/uploads")
async def upload(sid: str, file: UploadFile = File(...)) -> dict:
    """A tenant photo (or an audio clip). Send the returned `id` in a chat message's `attachments`."""
    workspace(sid)
    return (await _read_upload(file)).to_json()


@app.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str) -> FileResponse:
    try:
        up, path = media.get_upload(upload_id)
    except FileNotFoundError:
        raise HTTPException(404, "No such upload") from None
    return FileResponse(path, media_type=up.mime, headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400",
        "Content-Disposition": f'inline; filename="{up.name}"'})


@app.post("/api/sessions/{sid}/transcribe")
async def transcribe(sid: str, audio: UploadFile = File(...), browser_text: str = Form(""),
                     duration: float = Form(0)) -> dict:
    """Store a voice clip and transcribe it. The UI then sends the transcript as a chat message (or
    to /intake/voice) with `voice: {id, duration, source}` so the chat history shows clip + transcript."""
    workspace(sid)
    up = await _read_upload(audio)
    if up.kind != "audio":
        raise HTTPException(415, "Expected an audio clip")
    result = await media.transcribe(media.get_upload(up.id)[1].read_bytes(), up.mime, browser_text, RUNNER.mode)
    return {**result, "text": media.redact_names(result["text"]), "audio": {**up.to_json(), "duration": duration}}


class VoiceIntakeIn(BaseModel):
    text: str


@app.post("/api/sessions/{sid}/intake/voice")
async def voice_intake(sid: str, body: VoiceIntakeIn) -> dict:
    """Spoken intake -> form fields. Returns the fields and the A2UI updateDataModel messages that put
    them into the New intake form surface, so the paralegal can check them before submitting."""
    fields = await media.parse_intake(body.text, RUNNER.mode)
    source = fields.pop("_source", "rules")
    return {"fields": fields, "source": source, "transcript": media.redact_names(body.text),
            "a2ui": workspace(sid).intake_form_patch(fields)["messages"]}


# ------------------------------------------------------------------------- WebSocket


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """Client frames:
        {"type": "hello", "session_id"}                       -> snapshot of every surface + transcript
        {"type": "user_message", "session_id", "text", "attachments"?: [upload id], "voice"?: {id, duration, source}}
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
                async for e in space.user_message(str(frame.get("text", "")),
                                                  attachments=list(frame.get("attachments") or []),
                                                  voice=frame.get("voice")):
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
        root = UI_DIST.resolve()
        f = (root / path).resolve()
        inside = f == root or root in f.parents  # never serve a file outside ui/dist
        return FileResponse(f if path and inside and f.is_file() else root / "index.html")
