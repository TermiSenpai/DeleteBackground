#!/usr/bin/env bash
# DeleteBackground launcher for macOS / Linux.
# Creates a local virtual environment on first run, installs dependencies,
# then starts the FastAPI server.

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
PY="${PYTHON:-python3}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "[DeleteBackground] Creating virtual environment in .venv ..."
  "$PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -r "$ROOT/requirements.txt"
fi

HOST="${DBG_HOST:-127.0.0.1}"
PORT="${DBG_PORT:-8765}"

echo "[DeleteBackground] Starting on http://$HOST:$PORT"
if command -v open >/dev/null 2>&1; then
  open "http://$HOST:$PORT" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://$HOST:$PORT" >/dev/null 2>&1 || true
fi

exec "$VENV/bin/python" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
