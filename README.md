# TILES

An **explainable multi-agent system** for competitive board games, built as a
case study on **Azul**. TILES fields a decision stack of four specialized
agents — a **Validator**, a **Tactician**, a **Profiler**, and an
**Explainer** — that plays Azul locally (fast simulation) or live on
[buddyboardgames.com](https://buddyboardgames.com/azul) via browser
automation, records every move in an immutable ledger, and explains every
decision it makes.

*AIS PT07 Capstone Group 1 — Master of Technology in Artificial Intelligent
Systems, ISS, National University of Singapore.*

## Capabilities

| Capability | Where it lives | Try it |
|---|---|---|
| End-to-end autonomous gameplay on a **live website** (real browser, real platform, real opponents; Playwright driving the site's WebSocket protocol) | `backend/tiles/engine/` | Sessions → mode *live*, or `tiles live --room …` |
| Deterministic & **auditable decision pipeline** (validate → execute → persist with full state; replay anytime) | `tiles/orchestration/`, `tiles/ledger/` | Monitor → Replay → export JSON |
| **Adaptive intelligence via opponent profiling** (learn style online, 5 archetypes, predict next moves, bias MCTS) | `tiles/agents/profiler/`, `tacticians/mcts.py` | Play `mcts_profiled` vs anyone; Profiles view |
| **Visualization & monitoring** (real-time board, round-grouped move log, expandable snapshots, XAI panel) | `frontend/` | Monitor / Replay |
| Rule extraction & ingestion with an **accuracy benchmark** (RAG-to-Logic) | `tiles/rulebook/` | Rulebook view; `rule_extraction` experiment |
| Opponent-model **prediction accuracy** vs random/greedy baselines | `tiles/sim/prediction_eval.py` | `prediction_accuracy` experiment |
| 3–5 **player archetypes**, recovered unsupervised | `tiles/agents/profiler/archetypes.py` | `archetype_discovery` experiment |
| **Explainability dashboard** (why a move was chosen, how a profile was derived) | `tiles/agents/explainer/`, `frontend/.../XaiPanel.tsx` | Monitor, Profiles |
| Experiment tracking (ablation, tournaments/Elo, latency telemetry; MLflow-optional) | `tiles/experiments/`, `tiles/telemetry/` | Experiments view; `tiles experiment run …` |

## Quick start

```bash
./start.sh                 # backend :8000 + frontend :5173 (creates venv, node_modules, Playwright/Chromium)
```

Then open <http://localhost:5173>.

Manual setup:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,rl]'          # + [live] [telemetry] [llm] extras

tiles play --player Athena=mcts_profiled:simulations=300 --player Bruno=greedy --seed 7
tiles serve                         # API (+ built UI) at http://localhost:8000

cd ../frontend && npm install && npm run dev   # http://localhost:5173
```

### Run with Docker

```bash
docker build -t tiles . && docker run -p 8000:8000 -v tiles-db:/data tiles
docker compose --profile live up        # live-play image (bundled Chromium)
docker compose --profile telemetry up   # + MLflow UI at :5000
docker compose --profile dev up ui-dev  # hot-reload frontend at :5173
```

Set `ANTHROPIC_API_KEY` to enable the LLM explainer / LLM rule extractor.

## The web app

| View | What it shows |
|---|---|
| **Dashboard** | Ledger-wide stats: sessions, moves, experiments, win rate per Tactician, latency percentiles, archetype counts, recent games. |
| **Sessions** | Configure 2–4 seats (any Tactician with its parameters, or a *human* seat in live mode), Profiler/Explainer, seed, pacing; list, start, stop, delete sessions. |
| **Monitor** | Live board, round-grouped move log with timings, round summaries, system log, and the **XAI panel**: rationale, concept tags, candidate table (score/visits/prior), expected line, opponent profile cards. Live mode adds the lobby/join-link strip. |
| **Replay** | Scrub or auto-play any recorded game with the same board + XAI components. |
| **Profiles** | The Profile Analyzer: replay a session through any Profiler; archetype + confidence, traits, color/source/row distributions, score trajectory, and the archetype timeline. |
| **Experiments** | Launch any of the eight experiments with parameters, watch progress live, read results as summary / metrics / tables / charts, export JSON. |
| **Rulebook** | Browse the rulebook, run retrieval queries, inspect the extracted rules and their verification status. |
| **Agents** | The Decision Stack diagram and the registry of Tacticians, Profilers, Explainers with descriptions and parameters. |

## Experiments

Each experiment is a registered job (`tiles/experiments/kinds/`) with a
parameter schema, live progress, and a uniform result (summary, metrics,
tables, charts); results persist in the ledger.

| Kind | Question it answers |
|---|---|
| `profiler_ablation` | Does opponent profiling raise MCTS win rate (and at what latency cost)? — the headline result |
| `prediction_accuracy` | How well does the Profiler predict an opponent's next move vs uniform / static-greedy, by game phase? |
| `archetype_discovery` | Can five play styles be recovered unsupervised (k-means purity, classifier confusion)? |
| `tournament` | Elo ladder and head-to-head matrix across all Tacticians |
| `search_budget_sweep` | MCTS strength and latency vs simulation budget |
| `rule_extraction` | Rulebook → rule specs → engine verification accuracy |
| `latency_profile` | Per-Tactician decide/validate/explain latency percentiles from the ledger |
| `xai_coverage` | Explanation coverage, concept frequencies, and faithfulness of the stated primary driver |

```bash
tiles experiment list
tiles experiment run profiler_ablation --param games=20 --param simulations=300
tiles experiment run tournament --param games_per_pair=6 --output elo.json
```

## Live play on buddyboardgames.com

```bash
cd backend && pip install -e '.[live]' && playwright install chromium
tiles live --room tiles-demo --player Athena=mcts_profiled --player You=human --headed --db db/tiles.db
```

Or create a session with mode **live** in the UI. Each bot gets its own
Chromium seat; a `human` seat shows a share link with the room pre-filled.
The site is the dealer, the local engine is the referee: every move is
validated locally before it is emitted, opponents' moves are inferred from
the site's authoritative state for profiling, and the whole game lands in
the ledger like a local one. Site specifics are isolated in
`tiles/engine/protocol.py`, `browser_seat.py` and `dom_snapshot.py`.

## Repository layout

```
backend/tiles/
├── core/            # pure Azul engine: state, actions, rules, simulator, encodings
├── agents/
│   ├── base.py      # Decision Stack contracts (Tactician/Profiler/Explainer)
│   ├── catalog.py   # descriptions + parameter schemas for the registry (GET /api/agents)
│   ├── validator.py # deterministic rules gate + audit trail
│   ├── tacticians/  # random, greedy, minimax, MCTS (+ profiler-conditioned MCTS)
│   ├── profiler/    # features → archetypes → next-move prediction; post-hoc analysis
│   └── explainer/   # template + optional LLM rationales
├── orchestration/   # the per-turn pipeline: propose() / conclude() / run_turn()
├── ledger/          # immutable SQLite ledger: sessions, moves, rounds, profiles, experiments
├── rulebook/        # RAG rule ingestion: rulebook.md → RuleSpecs → verification
├── engine/          # live-play adapter (Playwright + the site's WebSocket protocol, DOM fallback)
├── sim/             # match runner, tournaments, ablation, prediction eval
├── experiments/     # registry, background runner, eight experiment kinds, CLI
├── telemetry/       # MLflow / JSONL experiment tracking
├── rl/              # PettingZoo AEC environment (optional extra)
├── server/          # FastAPI app factory, session manager, stats, routers/
└── cli.py           # play · live · analyze · tournament · ablate · experiment · serve
frontend/            # React + TypeScript: eight views, inline-SVG charts
```

## Tests

```bash
cd backend && .venv/bin/python -m pytest        # ~540 tests
cd frontend && npm run build                     # type-check + bundle
```

Covers rules legality/scoring/transitions (with a 100-tile conservation
invariant over full games), tactician correctness and strength, profiler
learning and prediction, the orchestration reject-loop, ledger round-trips,
live play against a fake site, the ML stack (MCTS/rollout/TD, Elo,
archetypes, sequence profiler), rule ingestion, every experiment kind, the
API routers and WebSocket streams, and the PettingZoo API.
