#!/usr/bin/env bash
# Start the backend (FastAPI, port 8080) and the UI (Vite, port 5173) in the background.
#   ./start.sh          demo mode (no Google Cloud needed)
#   ./start.sh live     real agent (Gemini + BigQuery)
# Optional: export GOOGLE_MAPS_API_KEY=... first for the interactive map with pins.
# Logs go to .run/; stop both with ./stop.sh
cd "$(dirname "$0")"
MODE="${1:-mock}"
mkdir -p .run

# Backend (pip only installs what is missing or changed)
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q -r api/requirements.txt
[ "$MODE" = "live" ] && .venv/bin/pip install -q -r agent/requirements.txt
A4I_AGENT_MODE="$MODE" nohup .venv/bin/uvicorn api.main:app --port 8080 > .run/backend.log 2>&1 &
echo $! > .run/backend.pid
echo "Backend started: http://localhost:8080 (agent: $MODE, log: .run/backend.log)"

# UI (reinstall packages when package.json changed)
if [ ! -d ui/node_modules ] || [ ui/package.json -nt ui/node_modules/.package-lock.json ]; then
  (cd ui && npm install --no-audit --no-fund)
fi
(cd ui && nohup npx vite --port 5173 > ../.run/ui.log 2>&1 & echo $! > ../.run/ui.pid)
echo "UI started:      http://localhost:5173 (log: .run/ui.log)"
