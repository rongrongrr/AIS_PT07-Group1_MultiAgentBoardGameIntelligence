# TILES

**T**ransparent **I**ntelligence for **L**earning, **E**xploration and **S**imulation: an explainable multi-agent platform that plays **Azul** on [buddyboardgames.com](https://buddyboardgames.com/azul) through automated Machine Players, records every move for replay and analysis, explains its decisions in plain language, and profiles how players behave.

AIS PT07 Capstone, Group 1 (NUS ISS). Measured results and their limits: [docs/EVALUATION.md](docs/EVALUATION.md). Feature-by-feature status: [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md).

## Quick Start

### Fastest: Docker (one command)

```bash
docker compose up --build        # first build downloads ~2 GB (Chromium + CPU PyTorch); later starts take seconds
```

Then open **http://localhost:8080**. Two containers: `backend` (FastAPI + Playwright/Chromium + PyTorch) and `frontend` (nginx serving the UI and proxying `/api`, including WebSockets, to the backend). Sessions, move history and the MLflow experiment store persist in Docker volumes (`docker compose down -v` wipes them).

- Browsers always run **headless** in a container (no display); the "Headed" option is ignored there.
- The containers need outbound internet access to reach buddyboardgames.com.
- Optional experiment-tracking UI: `docker compose --profile tracking up` then http://localhost:5000.
- Rebuild after code changes with `docker compose up --build`; stop with `docker compose down`.

### Without Docker

Prerequisites: Python 3.11+, Node.js 18+, Chromium (installed by Playwright).

```bash
cd backend
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt && playwright install chromium
uvicorn tiles.main:app --host 127.0.0.1 --port 8000   # API docs at http://localhost:8000/docs

cd ../frontend
npm install && npm run dev                          # http://localhost:5173 (proxies /api and WebSockets to :8000)
```

`TILES_DB_PATH` changes the database location; `TILES_MLFLOW_URI` the experiment store; `TILES_MLFLOW_DISABLED=1` turns tracking off.

### Play a game

1. Open the UI, enter a **Room Name** (max 20 characters) or click Random.
2. Choose **Headed** (watch the browsers, non-Docker only) or **Headless**.
3. Add 2-4 player slots: any registered bot, a remote model, or **Human** (joins through the room link).
4. **Create Session**, then **Start** in the Game Monitor. Review the finished game in the **Replay** tab.

## Machine Players

| Player | Strategy |
|---|---|
| **`MinimaxPlayer`** (default) | Depth-3 alpha-beta search over the exact in-round game tree with greedy playouts. Highest Elo in the round robin (1741); beats the lookahead player 81% and the heuristic 88%. |
| `MCTSPlayer` | UCT tree search over the same tree. Statistically tied with Minimax (Elo 1738). |
| `ConditionedMCTSPlayer`, `ConditionedMinimaxPlayer` | The same searches, but opponents are simulated as the play style the opponent model infers from their moves (profiler conditioning). |
| `TilesMCTS`, `TilesProfiledMCTS`, `TilesMinimax` | The teammate-built Decision Stack tacticians from `tiles/agents/` (PUCT MCTS with determinised redeals, the same with profiler-predicted opponent priors, paranoid minimax), running on the bit-packed core engine and bridged into live play by `tiles/bridge.py`. Strength vs the `ml/` players: see EVALUATION.md section 11. |
| `RolloutPlayer` | Shortlists heuristic moves and simulates the rest of the round for each. |
| `GreedyPlayer` | One-ply heuristic (wall points, line progress, bonus potential, floor penalties). Baseline. |
| `ColorCollectorPlayer`, `RusherPlayer`, `RecklessPlayer`, `BlockerPlayer` | The same heuristic engine with different weights: distinct play styles used to train and test the profilers. |
| `AdaptivePlayer`, `AdaptiveRolloutPlayer` | Switch weights / simulate opponents according to the archetype classifier (measured: no benefit, see EVALUATION.md section 6). |
| `TDPlayer` | Reinforcement learning: a linear value function learned by TD(0) self-play, roughly at parity with the heuristic. |
| `RandomPlayer` | Uniform random legal move (seedable). |
| *Remote models* | Any HTTP service can be registered as a player (`POST /api/players/register`); every move it returns is checked against the rules engine before it is played. |

## Explainability

Every decision is stored with: the model's top alternatives and scores, a **natural-language rationale** built from engine-derived facts (what the move completes and scores, floor spill, tiles passed to opponents, the first-player token, denial, margin over the next-best option, inferred opponent styles), and a one-line **commentary**. They appear in the Game Monitor, the **Replay** (play / pause / step / jump / speed / jump to round), and the export. A **rating widget** collects 1-5 ratings of understandability, usefulness and trustworthiness for the human-centred evaluation ([protocol](docs/HUMAN_EVALUATION_PROTOCOL.md); `python scripts/analyze_feedback.py`). Every claim in a rationale is verified against the game engine by the test suite.

## Profiling

- `BasicProfileAnalyzer`: colour / source / destination preferences, timing, rule-based style notes.
- `ArchetypeProfileAnalyzer`: logistic regression over 10 behaviour features (55-61% held-out accuracy, 5 styles).
- `SequenceProfileAnalyzer`: a Transformer over the player's move sequence, with saliency-based reasons (78% on the full game, 69% from the first 5 moves).
- `OpponentModel`: style posterior from observed moves and next-move prediction (81-98% top-1 for in-library opponents).

All are trained on simulated bot-vs-bot play, so labels on human games are hypotheses. Run per player from the **Profile Analyzing** tab or `POST /api/profiler/{session_id}/analyze`.

## Rulebook ingestion

`tiles/rules_ingest` turns rulebook text into structured rules: it chunks the text, ranks passages with TF-IDF, parses 16 rule fields, verifies them against the engine, and builds a `RulesConfig` that drives the validator and simulator. `docs/rules/azul_rules.md` is the corpus (16/16 fields match the engine; games played with the extracted rules are identical). A pluggable LLM extractor exists (stub-tested, not run live). Benchmark on generated rulebooks: `python scripts/rule_extraction_benchmark.py` (honest generalisation estimate: about 63% field accuracy on unseen phrasings; see EVALUATION.md section 14).

## Experiment tracking

Every finished live game is logged to MLflow automatically (config, scores, per-model latency, per-move telemetry, move ledger), and the evaluation scripts log with `--mlflow`. Optional and failure-safe. UI: `docker compose --profile tracking up` or `mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db`.

## Reproducing the experiments

All run from `backend/` and are seeded.

```bash
python scripts/tournament.py --games 100 --seed 1 --players GreedyPlayer MinimaxPlayer [--mlflow]
python scripts/elo_tournament.py --deals 10 --seed 3                 # Elo ratings + win-rate matrix
python scripts/evaluate_mcts.py --games 8 --seed 41                  # MCTS strength + profiler conditioning
python scripts/evaluate_opponent_model.py --games 12 --seed 5        # next-move prediction accuracy
python scripts/train_archetypes.py --games 1200 --seed 7             # feature-based archetype classifier
python scripts/train_sequence_profiler.py --games 1500 --seed 7      # Transformer / GRU sequence profiler
python scripts/train_td.py --games 800 --seed 3                      # TD(0) reinforcement learning
python scripts/tune_weights.py --generations 8 --seed 5              # genetic-algorithm weight tuning
python scripts/rule_extraction_benchmark.py --count 100 --seed 1     # rulebook extraction benchmark
python scripts/best_response.py / evaluate_adaptive.py / evaluate_lookahead.py   # earlier adaptive-play studies
```

`tiles/azul/game.py` is the simulation engine (move application, round scoring, tile recycling); `tiles/azul/rules.py` holds legality and scoring; `tiles/azul/config.py` the rule parameters.

## Tests

```bash
cd backend
python -m pytest                                  # offline tests (live test excluded); coverage report below
python -m pytest --cov=tiles --cov-report=term    # fails below 80% (currently ~90%)
python -m pytest -m live -s                       # live game on buddyboardgames.com (network + Chromium)
cd ../frontend && npm test && npx tsc -b          # UI tests (Vitest + Testing Library) and type-check
```

The orchestration tests run the production game loop against a fake platform backed by the simulation engine, so complete multi-round games are exercised with no browser; `tests/fixtures/live_frames.json` holds real frames captured from the live site. The browser-side JavaScript strings and the live site itself are covered only by live runs. Recorded completed live games (2, 3 and 4 players) and UI screenshots are in [docs/evidence/](docs/evidence/).

Debugging live play: `TILES_DEBUG_FRAMES=frames.jsonl uvicorn ...` logs every platform WebSocket frame.

## Project structure

```
backend/
  pyproject.toml, requirements.txt   `pip install -e .` gives the `tiles` command; requirements.txt is what Docker installs
  tiles/
    main.py                    FastAPI entry (live runtime API; optional UI hosting via TILES_UI_DIST)
    cli.py                     `tiles serve | play | tournament | ablate | predict-eval | verify-rules`
    azul/                      live-runtime rules: rules.py (legality, scoring), game.py (simulation), config.py
    engine/                    play_engine.py (Playwright browsers), action_executor.py, state_parser.py
    ml/                        players (greedy, rollout, minimax, mcts, td, remote), opponent_model.py,
                               archetypes.py, sequence_profiler.py, analyzers.py, elo.py, tuning.py, registry.py
    explain/explainer.py       rationales + commentary from engine-derived facts
    rules_ingest/              rulebook retrieval, extraction, benchmark, validator configuration
    core/                      bit-packed rules engine, 300-slot action space, simulator
    agents/                    Decision Stack: tacticians (PUCT MCTS, minimax, heuristics), profiler + move predictor,
                               template/LLM explainer, validator
    orchestration/             per-turn pipeline (validate -> decide -> explain -> record, with retry)
    sim/                       local matches, tournament, profiler ablation, prediction evaluation
    ledger/, telemetry/, rl/   SQLite ledger, MLflow/JSONL tracker, PettingZoo environment
    rulebook/                  second rule-extraction pipeline (rulebook text -> specs -> verified against core)
    bridge.py                  converts between the two engines; exposes core tacticians as live players
    tracking.py                MLflow logging of live games
    models/, routers/          SQLAlchemy + Pydantic; sessions, players, history, profiler, feedback
  scripts/                     training, tournament and evaluation scripts
  models/                      trained models (JSON / .pt)
  tests/
frontend/src/                  React + Zustand UI (config, monitor, replay, profile, rating) + Vitest tests
docs/                          evaluation, status, architecture, API, merge notes, protocol, evidence, corrections
docker-compose.yml             one-command run (+ optional MLflow UI profile)
.github/workflows/ci.yml       backend tests with coverage floor, frontend tests + build, Docker smoke test
```

`tiles/azul/game.py` is the simulation engine for the live runtime (move application, round scoring, tile recycling); `tiles/azul/rules.py` holds legality and scoring; `tiles/azul/config.py` the rule parameters. `tiles/core/` is an independent implementation; `tests/test_bridge.py` checks the two agree over full games. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/MERGE_NOTES.md](docs/MERGE_NOTES.md).

Command-line (no browser needed): `cd backend && pip install -e . && tiles tournament --player a=greedy --player b=mcts_profiled`, `tiles ablate`, `tiles verify-rules`, `tiles serve`.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/sessions` | Create a session (room <= 20 chars, name <= 16, 4 players max) |
| `GET` | `/api/sessions`, `/api/sessions/{id}` | List / get sessions |
| `POST` | `/api/sessions/{id}/start`, `/stop` | Start / stop (stop is a no-op on finished sessions) |
| `WS` | `/api/sessions/{id}/ws` | Live state, moves (with rationale), system log |
| `GET` | `/api/players`, `/api/players/{name}` | Registered players |
| `POST` / `DELETE` | `/api/players/register`, `/api/players/{name}` | Register / remove an external HTTP model |
| `POST` | `/api/player/action` | Reference implementation of the remote-model contract |
| `GET` | `/api/history/{id}` | Moves with board snapshots, explanations, rationales |
| `GET` | `/api/history/{id}/export` | Full game JSON ([format](backend/EXPORT_FORMAT.md)) |
| `GET` | `/api/history/{id}/state/{step}`, `/states` | State snapshots |
| `GET` | `/api/profiler/analyzers` | Available analyzers |
| `POST` | `/api/profiler/{id}/analyze?player_name=&analyzer_name=` | Profile a player |
| `POST` / `GET` | `/api/feedback`, `/api/feedback/summary`, `/api/feedback/{id}` | Explanation ratings and statistics |

## Status and known limitations

- **Live play works end to end** on buddyboardgames.com for 2-4 bot players (Docker and local): consecutive live games completed with no errors and no floor fallbacks at roughly 300-450 ms per move; ledger scores match the platform's final scores. Details and the defects found along the way: EVALUATION.md section 7.
- **The platform is a third-party dependency and has changed before.** It speaks JSON `{"type", "payload"}` over a plain WebSocket (not Socket.IO). Decisions, turn detection, dealing and scores use the platform's WebSocket state; the DOM parser is only a fallback. If the site changes again, run with `TILES_DEBUG_FRAMES` and compare against `tests/fixtures/live_frames.json`.
- A session is only `completed` if the final board shows a finished wall row; the host starts only once the platform has confirmed every expected player.
- **Not tested live:** human players joining through the room link (roster logic is unit-tested).
- **No participant data yet** for the human-centred explanation study (instrument and protocol are ready; the team has to run it).
- **LLM components** (rule extractor, explainer rewrite) are implemented against an interface and tested with stubs only; no API key was available to run them.
- **Profilers and the opponent model are trained on simulated bot play**; accuracy on human players is unknown. Opponent modelling inside the search gave at most a small gain (+2.7 margin points).
- Not implemented: authentication; the PRD's profiler ingest / insights endpoints.
- The API has no authentication and accepts any http(s) `platform_url` and remote-model URL; run it locally only.

## Tech stack

React 19 + TypeScript + Vite + Tailwind + Zustand (Vitest for tests); Python, FastAPI, SQLAlchemy, SQLite; Playwright (Chromium) against the platform's WebSocket protocol; numpy, scikit-learn and PyTorch for profiling and learning; MLflow for experiment tracking; Docker Compose + nginx for deployment.
