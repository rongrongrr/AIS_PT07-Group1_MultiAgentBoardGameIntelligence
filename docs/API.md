# TILES backend API

Base URL: `http://localhost:8000` (or `http://localhost:8080` through the Docker nginx proxy). Interactive docs at `/docs`.
The router code is in `backend/tiles/routers/`; the table in the [README](../README.md#api) is the summary.

## Sessions (`routers/sessions.py`)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/sessions` | Create a session. Body: `room_name` (<= 20 chars), `players` (2-4 slots of `{slot, type, name}` where `type` is a registered player name from `GET /api/players` or `human`), optional `platform_url`, `browser_mode` (`headless`/`headed`), `move_timeout_sec`, `stuck_abort_sec`, `profiler`. |
| `GET` | `/api/sessions`, `/api/sessions/{id}` | List / get. Status: `created`, `lobby`, `playing`, `completed`, `aborted`; `final_scores` and `winner` once finished. |
| `POST` | `/api/sessions/{id}/start` | Launch one Chromium bot per machine player; the host starts the game only after the platform confirmed every player. |
| `POST` | `/api/sessions/{id}/stop` | Abort a running session (no-op on a finished one). |
| `WS` | `/api/sessions/{id}/ws` | JSON events: `state` (board), `move` (action, rationale, alternatives, timing), `log`, `status`. |

## Players (`routers/players.py`)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/players`, `/api/players/{name}` | Registered Machine Players (built-in, the bridged `Tiles*` core tacticians, and remote models). |
| `POST` / `DELETE` | `/api/players/register`, `/api/players/{name}` | Register / remove an external HTTP model. Every move it returns is validated against the rules engine. |
| `POST` | `/api/player/action` | Reference implementation of the remote-model contract (`{state, player_index}` -> `GameAction`). |

## History, profiling, feedback

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/history/{id}` | Moves with board snapshots, explanations and rationales. |
| `GET` | `/api/history/{id}/export` | Full game JSON (format: [backend/EXPORT_FORMAT.md](../backend/EXPORT_FORMAT.md)). |
| `GET` | `/api/history/{id}/state/{step}`, `/states` | State snapshots for replay. |
| `GET` | `/api/profiler/analyzers` | Available analyzers (rule-based, learned archetype, sequence model). |
| `POST` | `/api/profiler/{id}/analyze?player_name=&analyzer_name=` | Profile one player of a finished or running session. |
| `POST` / `GET` | `/api/feedback`, `/api/feedback/summary`, `/api/feedback/{id}` | Per-move explanation ratings (human-evaluation instrument). |
| `GET` | `/api/health` | Liveness. |

## Command line (`tiles` entry point, `backend/tiles/cli.py`)

`tiles serve [--db PATH]` starts this API (set `TILES_UI_DIST=frontend/dist` to also serve the built UI); `tiles play | tournament | ablate | predict-eval | verify-rules` run offline simulations, evaluations and the rulebook check on the core engine (no browser needed).
