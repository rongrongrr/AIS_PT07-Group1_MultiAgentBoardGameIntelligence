# TILES — API server + built web UI (local simulation mode).
# For live play on buddyboardgames.com use Dockerfile.live instead.

# --- Stage 1: build the React frontend -------------------------------------
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npx vite build

# --- Stage 2: backend -------------------------------------------------------
FROM python:3.12-slim AS app
WORKDIR /app

# Install the package first so source edits don't bust the dep layer.
COPY backend/pyproject.toml backend/README.md ./backend/
COPY backend/tiles ./backend/tiles
RUN pip install --no-cache-dir ./backend

COPY --from=ui /ui/dist /app/ui
ENV TILES_UI_DIST=/app/ui \
    PYTHONUNBUFFERED=1

# The SQLite ledger lives on a volume so games survive restarts.
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["tiles", "serve", "--host", "0.0.0.0", "--port", "8000", "--db", "/data/tiles.db"]
