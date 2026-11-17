# api/ — WebSocket server

**Owner:** Karthik (deploy with Sid) · **Branch:** `agent` · **Contract:** [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#websocket-contract)

FastAPI app that exposes `GET /health` and `WS /ws`. It holds one ADK `Runner` for the `navigator` agent in [`agent/`](../agent/) and one ADK session per `session_id`.

## What it does per message

1. Receives `{"type": "user_message", "session_id", "text"}`.
2. Runs the agent and streams ADK events back as:
   - `status` when a tool call starts
   - `message` for agent text
   - `brief` when the agent produces the Stabilization Brief JSON
   - `error` on failure

## Planned layout

```
api/
  main.py            # FastAPI app, /ws handler, event translation
  requirements.txt
```

## Run locally

```bash
uvicorn api.main:app --reload --port 8080
# then connect a client to ws://localhost:8080/ws
```

Selvan's UI points at this URL locally, then at the Cloud Run URL after T+2:30.
