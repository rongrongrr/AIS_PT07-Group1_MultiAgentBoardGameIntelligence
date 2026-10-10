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
| `Replay` | play / pause / step (arrow keys, space) / jump / speed / jump-to-round, board **before and after** each move, a bar chart of the options the bot weighed, **profile overlay**, rating widget with progress and "next unrated", full or scores-only explanation condition |
| `StatusBanner` | plain-language state of a session (waiting for a human, who is thinking, why it aborted) |
| `ProfileAnalyzer` | run an analyzer (rule-based, learned archetype, sequence model) per player |
| `Leaderboard` | Elo ranking and win-rate matrix with 95% intervals from the latest saved tournament |

Also: quick-start presets and inline validation when creating a session, searchable / filterable session list, an optional **Tile letters** mode (B, Y, R, G, W on every tile) for colour-blind players, reduced-motion support, keyboard focus rings, and `?` help on technical terms.

If the backend sets `TILES_API_KEY`, the UI asks for the key once and stores it in `localStorage`.
