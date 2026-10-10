#!/usr/bin/env bash
# Start TILES backend (FastAPI :8000) and frontend (Vite :5173).
# Usage: ./start.sh
# Stop with Ctrl+C.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
API_URL="http://127.0.0.1:8000"
HEALTH_URL="$API_URL/api/health"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - EXIT INT TERM
  echo
  echo "Shutting down…"
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

ensure_backend() {
  if [[ ! -x "$VENV/bin/python" ]] ||
     ! "$VENV/bin/python" -c "import tiles" >/dev/null 2>&1; then
    echo "Backend venv missing or stale — rebuilding and installing…"
    python3 -m venv --clear "$VENV"
    "$VENV/bin/python" -m pip install -e "$BACKEND[dev]"
  fi
}

ensure_frontend() {
  if [[ ! -d "$FRONTEND/node_modules" ]]; then
    echo "Frontend deps missing — running npm install…"
    (cd "$FRONTEND" && npm install)
  fi
}

wait_for_api() {
  local i
  for i in $(seq 1 60); do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "Backend did not become healthy at $HEALTH_URL" >&2
  return 1
}

ensure_backend
ensure_frontend

echo "Starting backend at $API_URL …"
(
  cd "$BACKEND"
  exec "$VENV/bin/python" -m tiles.cli serve --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

wait_for_api
echo "Backend ready."

echo "Starting frontend at http://localhost:5173 …"
(
  cd "$FRONTEND"
  exec npm run dev -- --host 127.0.0.1 --port 5173
) &
FRONTEND_PID=$!

echo
echo "TILES is up:"
echo "  UI  → http://localhost:5173"
echo "  API → $API_URL"
echo "Ctrl+C to stop both."
echo

wait "$BACKEND_PID" "$FRONTEND_PID"
