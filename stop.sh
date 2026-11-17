#!/usr/bin/env bash
# Stop the backend and UI started by ./start.sh
cd "$(dirname "$0")"
for name in backend ui; do
  pidfile=".run/$name.pid"
  if [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null; then
    pkill -P "$(cat "$pidfile")" 2>/dev/null
    echo "Stopped $name"
  else
    echo "$name was not running"
  fi
  rm -f "$pidfile"
done
