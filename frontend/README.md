# TILES Frontend

React 18 + TypeScript + Vite single-page app for the TILES explainable
multi-agent Azul platform. Codes against `docs/API.md`.

## Views

- **New session** — configure 2–4 player slots (tactician per slot, MCTS
  simulation budget), profiler/explainer toggles, local vs live mode,
  seed and move pacing; creates and starts a session.
- **Monitor** — live board (factories, center, per-player pattern
  lines/wall/floor), WebSocket-driven move stream with polling fallback,
  round-grouped move log with per-move timing, and the **XAI panel**:
  explanation text + concept tags, candidate table (score/visits/prior),
  principal variation, and opponent profile cards.
- **Replay** — pick any recorded session and scrub through its moves;
  reuses the same board + XAI components on historical snapshots.

## Develop

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api → :8000
```

Start the backend first (`tiles serve` or `uvicorn tiles.server.app:app`)
or the UI will show "backend unreachable" placeholders.

## Build

```bash
npm run build        # type-checks then emits dist/
```

The FastAPI server serves `frontend/dist` statically in production, so a
plain `npm run build` is the only deploy step.
