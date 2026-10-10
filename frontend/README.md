# TILES web app

The browser interface for TILES: a single-page app written in React and
TypeScript and built with Vite. React is its only runtime dependency. Routing,
charts and state handling are all written by hand in this folder.

Start with the [main README](../README.md) for what TILES is and what each
view is for.

## Develop

```bash
npm install
npm run dev
```

This serves the app at <http://localhost:5173> and forwards anything under
`/api` to the backend at `http://localhost:8000`. Start the backend first
(`tiles serve`), otherwise the app shows "backend unreachable" placeholders and
a red status dot. To point at a backend somewhere else, set `TILES_API_PROXY`
before running `npm run dev`.

## Build

```bash
npm run build
```

This type-checks the code in strict mode and writes the app to `dist/`. The
backend serves that folder automatically, so building is the only deployment
step.

There are no automated tests for the web app. The strict type-check in the
build is the safety net.

## Views and their routes

The app uses hash routes, so every view has a shareable link.

| Route | View | Source |
|---|---|---|
| `#/dashboard` | Dashboard | `src/views/Dashboard.tsx` |
| `#/sessions` | Sessions | `src/views/Sessions.tsx` |
| `#/monitor/<session id>` | Monitor | `src/views/Monitor.tsx` |
| `#/replay/<session id>` | Replay | `src/views/Replay.tsx` |
| `#/profiles/<session id>` | Profiles | `src/views/Profiles.tsx` |
| `#/experiments/<run id>` | Experiments | `src/views/Experiments.tsx` |
| `#/rulebook` | Rulebook | `src/views/Rulebook.tsx` |
| `#/agents` | Agents | `src/views/Agents.tsx` |

## Code layout

```
src/
├── main.tsx           entry point
├── App.tsx            page shell: navigation, backend status dot, view switching
├── router.ts          the hash router
├── types.ts           data types matching the API, plus formatting helpers
├── styles.css         the one global stylesheet
├── api/client.ts      API calls and WebSocket connections with reconnect
├── views/             one file per view
└── components/
    ├── Board, Tile, MoveLog, XaiPanel, ProfileCard, RoundTable, SystemLog
    ├── SessionCard, StatTile, StatusBadge, ParamForm
    └── charts/        bar chart, line chart, matrix and legend, drawn as SVG
```

Two things are worth knowing before changing the code:

- **Forms are generated.** `ParamForm` builds the settings form for each
  Tactician and each experiment from the parameter list the backend sends, so
  adding a setting on the backend needs no change here.
- **Live updates are backed by polling.** The Monitor and Experiments views
  follow a game or run over a WebSocket, and also poll every few seconds so
  the page stays current if the socket drops.

The API these views call is documented in [docs/API.md](../docs/API.md).
