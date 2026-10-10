# TILES — Transparent Intelligence for Learning, Exploration, and Simulation

An **explainable multi-agent system** for competitive board games, built as a
case study on **Azul**. TILES fields a decision stack of four specialized
agents — a **Validator**, a **Tactician**, a **Profiler**, and an
**Explainer** — that plays Azul locally (fast simulation) or live on
[buddyboardgames.com](https://buddyboardgames.com/azul) via browser
automation, records every move in an immutable ledger, and explains every
decision it makes.

*AIS PT07 Capstone Group 1 — Master of Technology in Artificial Intelligent
Systems, ISS, National University of Singapore.*

## What it does

- **Plays Azul well**: a PUCT Monte Carlo Tree Search Tactician with
  heuristic priors, plus Greedy / Minimax / Random baselines.
- **Models opponents**: the Profiler learns each opponent's style online
  (Bayesian prior → posterior), classifies them into 5 archetypes, and
  predicts their next moves. Those predictions are **injected into the MCTS
  search** so the agent adapts its play to who it is facing.
- **Explains itself**: every move ships with a natural-language rationale
  derived from real search artifacts (Q-value margins, principal variation,
  profiler evidence) — template-based, optionally refined by an LLM.
- **Never breaks the rules**: a deterministic symbolic rules engine gates
  every proposed move; rules are also *extracted from the English rulebook*
  (RAG pipeline) and verified against the engine as an accuracy benchmark.
- **Measures everything**: immutable SQLite ledger with full board
  snapshots, per-move latency telemetry, Elo tournaments, and an ablation
  study isolating the Profiler's win-rate contribution (MLflow-optional).

## Quick start

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Watch an adaptive MCTS agent beat a greedy bot, with explanations:
tiles play --player Athena=mcts_profiled:simulations=300 --player Bruno=greedy --seed 7

# Benchmarks from the report deliverables:
tiles predict-eval --games 10          # opponent-model prediction accuracy
tiles verify-rules                     # rulebook extraction accuracy
tiles ablate --games 10                # profiler ablation (win-rate uplift)
tiles tournament --games-per-pair 2    # Elo standings across all tacticians
```

### Web UI (live monitor + XAI dashboard + replay)

```bash
# terminal 1 — API server
cd backend && source .venv/bin/activate && tiles serve

# terminal 2 — frontend dev server (or `npm run build` once and let
# `tiles serve` host the built app at http://localhost:8000)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Create a session in the UI (2–4 players, any mix of tacticians), start it,
and watch the board, the move log, and the **XAI panel** (why each move was
chosen, what was considered, who the opponent is) update live.

### Run with Docker

Everything (backend + built UI) ships as one container:

```bash
docker build -t tiles .          # or: docker compose up tiles
docker run -p 8000:8000 -v tiles-db:/data tiles
# UI + API at http://localhost:8000
```

Variants via compose profiles:

```bash
docker compose --profile live up        # live-play image (bundled Chromium)
docker compose --profile telemetry up   # + MLflow UI at :5000
docker compose --profile dev up ui-dev  # hot-reload frontend at :5173
```

The SQLite ledger persists in the `tiles-db` volume. Set
`ANTHROPIC_API_KEY` (see `docker-compose.yml`) to enable the LLM explainer.

### Live play on buddyboardgames.com

```bash
cd backend && pip install -e '.[live]' && playwright install chromium
```

Then create a session with mode **live** in the UI (or via `POST
/api/sessions`), giving a room name. Each bot gets its own Chromium seat;
add a `human` slot and share the room link to play against the agents
yourself. See `tiles/engine/` for the adapter design.

## Repository layout

```
backend/tiles/
├── core/            # pure Azul engine: state, actions, rules, simulator, encodings
├── agents/
│   ├── base.py      # Decision Stack contracts (Tactician/Profiler/Explainer)
│   ├── validator.py # deterministic rules gate + audit trail
│   ├── tacticians/  # random, greedy, minimax, MCTS (+ profiler-conditioned MCTS)
│   ├── profiler/    # features → archetypes → next-move prediction
│   └── explainer/   # template + optional LLM rationales
├── orchestration/   # the per-turn pipeline (sense→profile→decide→validate→…)
├── ledger/          # immutable SQLite move ledger + export
├── rulebook/        # RAG rule ingestion: rulebook.md → RuleSpecs → verification
├── engine/          # live-play adapter (Playwright + Socket.IO)
├── sim/             # match runner, tournaments, ablation, prediction eval
├── rl/              # PettingZoo AEC environment (optional extra)
├── telemetry/       # MLflow / JSONL experiment tracking
└── server/          # FastAPI: sessions, WebSocket live updates, history
frontend/            # React + TypeScript: config, live monitor, XAI panel, replay
docs/                # ARCHITECTURE.md, API.md
```

## Tests

```bash
cd backend && .venv/bin/python -m pytest        # full suite
```

Covers rules legality/scoring/transitions (with a 100-tile conservation
invariant over full games), tactician correctness and strength, profiler
learning and prediction accuracy, the orchestration reject-loop, ledger
round-trips, rulebook extraction accuracy, the live-state translator, and
the PettingZoo API (when the `rl` extra is installed).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the system design and how
  it maps to the project report.
- [docs/API.md](docs/API.md) — the REST/WebSocket contract between backend
  and frontend.
- [docs/STAGE2_PLAN.md](docs/STAGE2_PLAN.md) — remaining work, the
  experiments the final report needs, and the report outline.
