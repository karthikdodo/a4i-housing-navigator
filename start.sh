#!/usr/bin/env bash
# Start the backend (FastAPI, port 8080) and the UI (Vite, port 5173) in the background.
#   ./start.sh          demo mode (no Google Cloud needed)
#   ./start.sh live     real agent (Gemini + BigQuery)
# Logs go to .run/; stop both with ./stop.sh
cd "$(dirname "$0")"
MODE="${1:-mock}"
mkdir -p .run

# Backend
[ -x .venv/bin/uvicorn ] || { python3 -m venv .venv && .venv/bin/pip install -r api/requirements.txt; }
[ "$MODE" = "live" ] && .venv/bin/pip install -q -r agent/requirements.txt
A4I_AGENT_MODE="$MODE" nohup .venv/bin/uvicorn api.main:app --port 8080 > .run/backend.log 2>&1 &
echo $! > .run/backend.pid
echo "Backend started: http://localhost:8080 (agent: $MODE, log: .run/backend.log)"

# UI
[ -d ui/node_modules ] || (cd ui && npm install)
(cd ui && nohup npx vite --port 5173 > ../.run/ui.log 2>&1 & echo $! > ../.run/ui.pid)
echo "UI started:      http://localhost:5173 (log: .run/ui.log)"
