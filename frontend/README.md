# TILES frontend

React 19 + TypeScript + Vite + Tailwind + Zustand. In Docker it is built and served by nginx, which also proxies `/api`
(including WebSockets) to the backend; see the [root README](../README.md).

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api and WebSockets to http://localhost:8000
npm test           # Vitest + Testing Library
npm run build      # type-check (tsc -b) and production build into dist/
```

| Component | Purpose |
|---|---|
| `SessionConfig` | create a session: room, headless/headed, 2-4 players (bots, remote models, human) |
| `GameMonitor` | live board, round-grouped move log with rationales, system log, live **Profiler Insights** |
| `Replay` | play / pause / step / jump / speed / jump-to-round, **profile overlay**, rating widget |
| `ProfileAnalyzer` | run an analyzer (rule-based, learned archetype, sequence model) per player |
| `Leaderboard` | Elo ranking and win-rate matrix from the latest saved tournament |

If the backend sets `TILES_API_KEY`, the UI asks for the key once and stores it in `localStorage`.
