# api/: WebSocket server that also serves the UI

**Owner:** April · **Branch:** `api` · **Contract:** [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#websocket-contract)

One FastAPI app, deployed as **one Cloud Run service**, does everything:

```
https://<service>.run.app/         → Selvan's UI (static files from ui/)
https://<service>.run.app/health   → {"ok": true}
wss://<service>.run.app/ws         → WebSocket → navigator agent → BigQuery / Gemini
```

One URL, one deploy. The UI and API share an origin, so there's no CORS setup and no URL to configure in the UI.

## What `/ws` does per message

1. Receives `{"type": "user_message", "session_id", "text"}`.
2. Runs the agent and streams back `status`, `message`, `brief`, and `error` events.

The event mapping is already written and tested: copy `run_turn()` from the docstring at the top of [`agent/navigator/agent.py`](../agent/navigator/agent.py). It also covers SSE streaming, skipping duplicate partial events, and where the brief comes from.

## Layout

```
api/
  main.py            FastAPI app: /health, /ws, then the UI mounted at /
  requirements.txt   fastapi, uvicorn[standard]
```

Mount the UI **last**, after `/health` and `/ws`, or it will swallow those routes:

```python
from fastapi.staticfiles import StaticFiles
# ... @app.get("/health") and @app.websocket("/ws") above ...
app.mount("/", StaticFiles(directory="ui/dist", html=True), name="ui")   # or "ui" if no build step
```

## Run locally (from the repo root)

```bash
.venv/bin/pip install -r agent/requirements.txt -r api/requirements.txt
PYTHONPATH=agent .venv/bin/uvicorn api.main:app --reload --port 8080
# open http://localhost:8080 for the UI, or connect a client to ws://localhost:8080/ws
```

Optional: a `MOCK=1` mode that replays a recorded event sequence lets Selvan build the UI without waiting ~40 s for Gemini on every test.

Deploy: see [`infra/README.md`](../infra/README.md).
