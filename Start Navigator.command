#!/usr/bin/env bash
# Double-click in Finder to start the Stabilization Navigator (demo mode).
cd "$(dirname "$0")" || exit 1
echo "== Installing UI packages for this Mac (first run takes a minute) =="
(cd ui && npm install --no-audit --no-fund) || { echo "npm install failed"; read -r -p "Press Enter to close"; exit 1; }
touch ui/node_modules/.package-lock.json
./stop.sh >/dev/null 2>&1
./start.sh "${1:-mock}"
sleep 4
echo
echo "== Backend health =="; curl -s http://localhost:8080/health || echo "backend not answering yet: see .run/backend.log"
echo; echo "== Last backend log lines =="; tail -n 8 .run/backend.log
echo; echo "== Last UI log lines =="; tail -n 8 .run/ui.log
echo; echo "Open http://localhost:5173 . You can close this window; the servers keep running. Stop them with 'Stop Navigator.command'."
