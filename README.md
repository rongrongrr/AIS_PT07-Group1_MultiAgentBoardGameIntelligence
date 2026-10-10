# TILES

**T**ransparent **I**ntelligence for **L**earning, **E**xploration and **S**imulation: an explainable multi-agent platform that plays **Azul** on [buddyboardgames.com](https://buddyboardgames.com/azul) through automated Machine Players, records every move for replay and analysis, and profiles how players behave.

AIS PT07 Capstone, Group 1 (NUS ISS). See [docs/EVALUATION.md](docs/EVALUATION.md) for measured results and their limits.

## Quick Start

### Prerequisites

- **Python 3.11+** (developed on 3.11)
- **Node.js 18+**
- **Chromium** (installed by Playwright)

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API docs: `http://localhost:8000/docs`. The database path can be changed with `TILES_DB_PATH`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api and WebSockets to :8000)
```

### 3. Play a game

1. Open `http://localhost:5173`, enter a **Room Name** (max 20 characters) or click Random.
2. Choose **Headed** (watch the browsers) or **Headless**.
3. Add 2-4 player slots: any registered bot, or **Human** (joins through the room link).
4. **Create Session**, then **Start** in the Game Monitor.

Each bot gets its own Chromium window, joins the room, and plays autonomously. Bots wait in the lobby for human slots before the host bot starts the game.

## Machine Players

| Player | Strategy |
|---|---|
| `GreedyPlayer` | Heuristic: scores every legal move on wall points, line progress, end-game bonus potential and floor penalties. The balanced baseline. |
| `ColorCollectorPlayer`, `RusherPlayer`, `RecklessPlayer`, `BlockerPlayer` | The same engine with different weights, giving distinct play styles (colour loyalty, fast small rows, big piles and floor tolerance, denying opponents' colours). Used to train and test the profiler. |
| **`RolloutPlayer`** (recommended) | Lookahead: shortlists the heuristic's best moves, simulates the rest of the round for each, and picks the one with the best resulting board. Wins 98% of simulated games against `GreedyPlayer` (73 vs 42 points). |
| `AdaptivePlayer` | Watches opponent moves, classifies their style, and switches to the weights that did best against that style in simulation. |
| `AdaptiveRolloutPlayer` | `RolloutPlayer` that simulates each opponent as its inferred archetype. Measured to give no benefit over `RolloutPlayer` (see [EVALUATION.md](docs/EVALUATION.md)); kept for future work. |
| `RandomPlayer` | Uniform random legal move (optionally seeded). Baseline. |

Every decision records its top alternatives and scores (`last_explanation`); they are stored in the ledger and shown under "Why this move" in the move log.

## Profiling

- `BasicProfileAnalyzer`: colour/source/destination preferences, timing, score trajectory, rule-based style notes.
- `ArchetypeProfileAnalyzer`: the above plus a learned archetype with probabilities and the behavioural features that drove the label (logistic regression, 10 features). **Trained on simulated bot-vs-bot play**, so labels on human games are hypotheses.

Analysis is run per player from the **Profile Analyzing** tab (or `POST /api/profiler/{session_id}/analyze`).

## Reproducing the experiments

All run from `backend/` and are seeded.

```bash
python scripts/tournament.py --games 100 --seed 1                # Greedy vs Random win rates + 95% CI
python scripts/train_archetypes.py --games 1200 --seed 7         # self-play -> classifier, held-out accuracy
python scripts/best_response.py --games 100 --seed 21            # best counter-style per opponent archetype
python scripts/evaluate_adaptive.py --games 100 --seed 99        # adaptive vs static baseline, unseen deals
python scripts/evaluate_lookahead.py --games 25 --seed 66        # lookahead strength + opponent modelling in search
```

`app/azul/game.py` is the simulation engine behind these (move application, round scoring, tile recycling); `app/azul/rules.py` holds legality and scoring.

## Tests

```bash
cd backend
python -m pytest                                  # 217 offline tests (live test excluded)
python -m pytest --cov=app --cov-report=term      # with coverage; fails below 80% (currently 97%)
python -m pytest -m live -s                       # live game on buddyboardgames.com (network + Chromium)
cd ../frontend && npx tsc -b                      # type-check
```

The orchestration tests run the production game loop against a fake platform backed by the simulation engine, so complete multi-round games are exercised with no browser, and `tests/fixtures/live_frames.json` holds real frames captured from the live site. The browser-side JavaScript strings and the live site itself are covered only by live runs (below).

### Live runs

```bash
cd backend && uvicorn app.main:app --port 8000        # start the API, then create/start a session from the UI or API
TILES_DEBUG_FRAMES=frames.jsonl uvicorn ...           # optional: log every platform WebSocket frame for debugging
```

Recorded completed live games (2, 3 and 4 players) are in [docs/evidence/](docs/evidence/).

## Project structure

```
backend/
  app/
    main.py                    FastAPI entry
    azul/rules.py              legal moves, scoring, bonuses
    azul/game.py               state transitions + full-game simulation
    engine/play_engine.py      Playwright browsers, game-over / new-round detection
    engine/action_executor.py  Socket.IO chooseTiles/placeTiles
    engine/state_parser.py     Socket.IO + DOM state parsing
    ml/greedy_player.py        heuristic player + style variants + explanations
    ml/adaptive_player.py      profile-conditioned player
    ml/archetypes.py           behaviour features + archetype classifier
    ml/analyzers.py            profile analyzers + registry
    ml/registry.py             player registry
    models/{db,schemas}.py     SQLAlchemy + Pydantic
    routers/                   sessions, players, history, profiler
  scripts/                     tournament, training and evaluation scripts
  models/                      trained classifier + best-response table (JSON)
  tests/
frontend/src/                  React + Zustand UI (config, monitor, profile)
docs/                          reports, evaluation, design notes
```

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/sessions` | Create a session (validated: room <= 20 chars, name <= 16, 4 players max) |
| `GET` | `/api/sessions`, `/api/sessions/{id}` | List / get sessions |
| `POST` | `/api/sessions/{id}/start`, `/stop` | Start / stop (stop is a no-op on finished sessions) |
| `WS` | `/api/sessions/{id}/ws` | Live state, moves, system log |
| `GET` | `/api/players`, `/api/players/{name}` | Registered players |
| `GET` | `/api/history/{id}` | Moves with board snapshots and explanations |
| `GET` | `/api/history/{id}/export` | Full game JSON ([format](backend/EXPORT_FORMAT.md)) |
| `GET` | `/api/history/{id}/state/{step}`, `/states` | State snapshots |
| `GET` | `/api/profiler/analyzers` | Available analyzers |
| `POST` | `/api/profiler/{id}/analyze?player_name=` | Profile a player |

## Status and known limitations

- **Live play works end to end** on buddyboardgames.com for 2-4 bot players: after the final fixes, 7 consecutive live games completed (3 four-player, 4 two-player) with no errors and no floor fallbacks, at roughly 300-440 ms per move; ledger scores match the platform's final scores. Details and the defects found along the way: [docs/EVALUATION.md](docs/EVALUATION.md) section 7.
- **The platform is a third-party dependency and has changed before.** It now speaks JSON `{"type", "payload"}` over a plain WebSocket (not Socket.IO), and the client captures the page's socket object via an injected script. Decisions, turn detection, dealing and scores all use the platform's WebSocket state; the DOM parser is only a fallback. If the site changes again, run with `TILES_DEBUG_FRAMES` set and compare against `tests/fixtures/live_frames.json`.
- A session is only marked `completed` if the final board shows a finished wall row; otherwise it is `aborted` with the reason. The host starts only once the platform has confirmed every expected player is in the room.
- **Not tested live:** human players joining through the room link (roster logic is unit-tested), headed mode over long sessions.
- **Strength:** `RolloutPlayer` is a strong heuristic-plus-lookahead player, not a trained or exhaustive-search one. Two-player mirror matches between lookahead players are low-scoring (live 10-56 points); 3-4 player games score 30-70 per player.
- **Profiling** is trained on simulated bot play only; archetype labels on human games are hypotheses (55% accurate on held-out simulated styles).
- Not implemented: rulebook ingestion (RAG/LLM), MCTS/minimax players, MLflow tracking, replay playback controls, external-model REST endpoints, authentication.
- The API has no authentication and accepts any http(s) `platform_url`; run it locally only.

## Tech stack

React 19 + TypeScript + Vite + Tailwind + Zustand; Python, FastAPI, SQLAlchemy, SQLite; Playwright (Chromium) with the platform's Socket.IO protocol; numpy + scikit-learn for profiling.
