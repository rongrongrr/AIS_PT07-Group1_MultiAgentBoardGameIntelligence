# TILES Frontend

React 18 + TypeScript + Vite single-page app for the TILES explainable
multi-agent Azul platform. Codes strictly against the backend REST/WebSocket API.

## Views (hash routes)

| Route | View | What it shows |
|---|---|---|
| `#/dashboard` | Dashboard | `GET /api/stats`: session/move/experiment counts, win rate per tactician, pipeline latency, archetype counts, recent sessions |
| `#/sessions` | Sessions | New-session form (local/live, 2–4 seats with per-tactician params from `/api/agents`, profiler, explainer, seed, pacing, live room options) + session list with start/stop/delete |
| `#/monitor/<id>` | Monitor | Live board, score header, round-grouped move log, round results, system log, live-mode status strip (join link, waiting-for-humans), XAI panel; WebSocket with polling fallback |
| `#/replay/<id>` | Replay | Scrubber with play/pause and speed, round jumps, round-results table, board + XAI panel on historical snapshots |
| `#/profiles/<id>` | Profiles | The Profile Analyzer: `POST /api/profiles/{id}/analyze?profiler=` → archetype, traits, color/source/destination/row splits, score trajectory, archetype timeline, concept counts; archetype legend |
| `#/experiments/<id>` | Experiments | Experiment types with schema-generated param forms, run list with progress, live progress/log over WebSocket, result renderer (summary, metrics, tables, bar/line/matrix charts with table twins, raw JSON) |
| `#/rulebook` | Rulebook | Section browser, TF-IDF search, extracted rules with verification status and accuracy (deterministic or LLM extractor) |
| `#/agents` | Agents | Decision Stack pipeline diagram + registry cards for tacticians / profilers / explainers / validator |

## Layout

```
src/
├── App.tsx            shell: nav, backend health dot, capability badges, routing
├── router.ts          hash router (#/view/<id>)
├── types.ts           DTOs mirroring the API contract + formatting helpers
├── api/client.ts      fetch wrapper, session/experiment WebSockets with reconnect
├── components/
│   ├── Board, Tile, MoveLog, XaiPanel, ProfileCard, RoundTable, SystemLog
│   ├── SessionCard, StatTile, StatusBadge, ParamForm
│   └── charts/        hand-rolled SVG BarChart, LineChart, Matrix, SeriesChart (+ palette)
└── views/             one file per view
```

Charts follow the dataviz method: fixed-order categorical palette, thin
marks with rounded data-ends, hairline grid, title tooltips, a legend for
two or more series, and a table-view twin for every rendered series.

## Develop

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api → :8000
```

Start the backend first (`tiles serve`) or the UI shows "backend
unreachable" placeholders and a red health dot.

## Build

```bash
npm run build        # type-checks (strict) then emits dist/
```

The FastAPI server serves `frontend/dist` statically in production, so a
plain `npm run build` is the only deploy step.
