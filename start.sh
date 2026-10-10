#!/usr/bin/env bash
# Start the TILES backend (FastAPI :8000) and frontend dev server (Vite :5173).
#
#   ./start.sh            # local + live play (installs Playwright + Chromium)
#
# Stop with Ctrl+C. The backend venv and frontend node_modules are created
# on first run (and rebuilt automatically if they look broken).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
API_HOST="${TILES_API_HOST:-127.0.0.1}"
API_PORT="${TILES_API_PORT:-8000}"
UI_PORT="${TILES_UI_PORT:-5173}"
API_URL="http://$API_HOST:$API_PORT"
HEALTH_URL="$API_URL/api/health"
EXTRAS="dev,rl,live"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - EXIT INT TERM
  echo
  echo "Shutting down…"
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

ensure_backend() {
  if [[ ! -x "$VENV/bin/python" ]] ||
     ! "$VENV/bin/python" -c "import tiles, fastapi, uvicorn" >/dev/null 2>&1; then
    echo "Backend venv missing or stale — rebuilding and installing…"
    rm -rf "$VENV"
    python3 -m venv "$VENV"
    "$VENV/bin/python" -m pip install -q -e "$BACKEND[$EXTRAS]"
  fi
  "$VENV/bin/python" -c "import playwright" >/dev/null 2>&1 ||
    "$VENV/bin/python" -m pip install -q -e "$BACKEND[live]"
  "$VENV/bin/python" -m playwright install chromium >/dev/null 2>&1 ||
    echo "Warning: Chromium install failed — live play may be unavailable." >&2
}

ensure_frontend() {
  if [[ ! -d "$FRONTEND/node_modules" ]]; then
    echo "Frontend deps missing — running npm install…"
    (cd "$FRONTEND" && npm install)
  fi
}

wait_for_api() {
  local i
  for i in $(seq 1 80); do
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

if lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $API_PORT is already in use by:" >&2
  lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN >&2
  echo "Stop that process first, or run with TILES_API_PORT=<free port>." >&2
  exit 1
fi

echo "Starting backend at $API_URL …"
(
  cd "$BACKEND"
  exec "$VENV/bin/python" -m tiles.cli serve --host "$API_HOST" --port "$API_PORT"
) &
BACKEND_PID=$!

wait_for_api
echo "Backend ready."

echo "Starting frontend at http://localhost:$UI_PORT …"
(
  cd "$FRONTEND"
  exec npm run dev -- --host 127.0.0.1 --port "$UI_PORT"
) &
FRONTEND_PID=$!

echo
echo "TILES is up:"
echo "  UI  → http://localhost:$UI_PORT"
echo "  API → $API_URL  (OpenAPI docs at $API_URL/docs)"
echo "Ctrl+C to stop both."
echo

wait "$BACKEND_PID" "$FRONTEND_PID"
