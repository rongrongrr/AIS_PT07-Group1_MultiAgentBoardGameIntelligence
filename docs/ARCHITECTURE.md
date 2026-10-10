# TILES Architecture

This document maps the codebase to the design in the progress report
(*TILES: Architecting an Explainable Multi-Agent System for Competitive
Board Games*). Read it top-down; each section names the modules that
implement it.

## 1. Design principles

1. **The local rules engine is the single source of truth.** The previous
   iteration used the live website as the game engine, which made round
   transitions and game-over detection fragile. TILES inverts this: a pure,
   deterministic engine (`tiles/core/`) owns legality, scoring, and state
   transitions; the live platform is just an *adapter* that mirrors state in
   and pushes actions out (`tiles/engine/`).
2. **Agents are interfaces, not classes.** Every Decision Stack role sits
   behind an ABC (`tiles/agents/base.py`) and a registry, so a trained RL
   Tactician or a transformer Profiler drops in without touching the
   orchestrator, server, or UI.
3. **Explainability is data-first.** Tacticians must return a
   `SearchReport` (candidates, Q-values, visits, priors, principal
   variation, per-component heuristic breakdowns). Explanations are derived
   from these artifacts — never invented after the fact.
4. **Everything is replayable.** Every turn produces a `TurnRecord` with
   full before/after board snapshots, validation trace, explanation, and
   timing, persisted append-only in SQLite (`tiles/ledger/`).

## 2. The core engine (`tiles/core/`)

- `state.py` — `GameState` / `PlayerBoard`. Optimized for MCTS cloning:
  walls are 25-bit integers, tile pools are 5-int count vectors. A semantic
  JSON view (`to_dict`) serves the ledger, Explainer, and frontend — the
  dual-representation strategy from the report (bitboard-style for search,
  JSON for humans).
- `actions.py` — `Action` with a stable 300-slot `action_id` space
  (10 sources × 5 colors × 6 destinations), matching the report's action
  space analysis and giving RL consumers a fixed action mask.
- `rules.py` — legality as named predicates (`wall_slot_open`,
  `line_color_matches`, …) returning machine-readable `RuleViolation`s;
  adjacency scoring; wall-tiling round resolution; floor penalties with the
  zero floor; end-game bonuses; `step()` as the single transition function.
- `simulator.py` — the stochastic part (bag draws, lid refill, factory
  dealing) kept separate so search can determinize it and the live adapter
  can skip it.
- `encode.py` — flat float observation vector for neural consumers.

Invariant tested end-to-end: the 100 physical tiles are conserved through
every transition of full random games (`tests/test_rules.py`).

## 3. The Decision Stack (`tiles/agents/`)

```
            ┌────────────────────────────────────────────────┐
            │              TurnPipeline (orchestration)       │
            │                                                │
 sense ──► profile ──► decide ──► validate ──► execute ──► observe ──► explain
            │Profiler│   │Tactician│  │Validator│ (rules.step)  │Profiler│  │Explainer│
            │        │   ▲         │      │ reject + trace     │
            │        └───┘ opponent│      └──────► retry ──────┘
            │            policy    │              (≤2, then greedy fallback)
            └────────────────────────────────────────────────┘
```

### Validator (`validator.py` + `orchestration/turn_graph.py`)
The deterministic authority. Wraps `core.rules.check_action`; every check
is recorded in an audit trail. The orchestrator gives it coordination
authority: a rejected proposal is bounced back to the Tactician once with
the violated predicate attached, then falls back to the best heuristic
legal move — the self-correcting loop from the report, with zero
possibility of an illegal move reaching the board. The pipeline nodes map
1:1 onto the report's LangGraph design; the implementation is a
framework-free deterministic graph (same node/edge semantics, no LLM in
the routing path, trivially portable to LangGraph if required).

### Tacticians (`tacticians/`)
- `random`, `greedy` — report baselines. Greedy uses a weighted,
  *decomposed* heuristic (`heuristics.py`): immediate placement points,
  line progress, floor penalty, first-player token value, end-game bonus
  potential, and **denial** (taking tiles opponents visibly need). The
  decomposition doubles as XAI evidence.
- `minimax` — paranoid depth-limited alpha-beta within the current round
  (drafting is deterministic between redeals), the third report baseline.
- `mcts` — PUCT search: priors from a heuristic softmax, determinized
  redeals at round boundaries, epsilon-greedy rollouts, `tanh`-normalized
  leaf evaluation.
- `mcts_profiled` — the same search with the report's core idea: at
  opponent decision nodes the prior is blended 70/30 with the **Profiler's
  predicted move distribution**, so search effort concentrates on futures
  the *actual* opponent is likely to create.

### Profiler (`profiler/`)
- `features.py` — per-move features and per-player trait accumulation
  (color bias, center/floor rates, completion rate, denial, risk, tempo).
- `archetypes.py` — 5 named archetypes (aggressive_blocker,
  cautious_optimizer, set_collector, greedy_scorer, risk_taker) via
  similarity to trait signatures, plus a pure-Python k-means for offline
  archetype discovery. (Deliverable: 3–5 archetypes.)
- `predictor.py` — opponent modeling: each opponent is a softmax policy
  over the shared heuristic components with per-player weights learned
  online (multiplicative-weights updates). Cold start is handled by a
  population prior blended out as evidence accumulates — the Bayesian
  prior→posterior transition from the report. (Deliverable: next-move
  prediction accuracy, benchmarked by `tiles predict-eval` against uniform
  and static-greedy baselines.)

### Explainer (`explainer/`)
- `templates.py` — deterministic rationale: primary driver (largest
  weighted heuristic component), margin vs. runner-up, search evidence
  (simulations, principal variation), profiler evidence (archetype), and
  concept tags (COMPLETES_LINE, BLOCKS_OPPONENT, FLOOR_SACRIFICE, …).
- `llm.py` — optional Claude-refined commentary; silently falls back to
  the template. The LLM is *never* in the decision path.

## 4. Rule ingestion (`tiles/rulebook/`)

The RAG-to-Logic pipeline, sized to this project: `rulebook.md` (English
rules) → TF-IDF chunk retrieval (`ingest.py`) → structured `RuleSpec`s
mapping sentences to engine predicates and parameters (`extract.py`,
deterministic extractor + optional LLM extractor) → `verify.py`, which
checks every spec **against the engine as ground truth** and reports an
accuracy score (`tiles verify-rules`). This keeps generative components
out of the real-time path while still demonstrating rulebook
understanding — and gives the report its extraction-accuracy benchmark.

## 5. Persistence & telemetry

- `ledger/store.py` — append-only SQLite (WAL): sessions, moves
  (full `TurnRecord` JSON), rounds, profiles. Powers replay, export,
  profiling datasets, and future RL training data.
- `telemetry/` — MLflow when installed, JSONL otherwise; used by the
  ablation study.
- `sim/` — `match.py` (local games through the TurnPipeline),
  `tournament.py` (round-robin + Elo), `ablation.py` (greedy vs mcts vs
  mcts_profiled against a fixed blocker opponent — isolates the Profiler's
  win-rate contribution), `prediction_eval.py` (opponent-model accuracy).

## 6. Interfaces

- `server/app.py` — FastAPI; sessions run on worker threads and stream
  WS events (contract: `docs/API.md`). Serves the built frontend.
- `frontend/` — React + TypeScript: session config, live monitor with the
  board and the XAI sidebar (explanation, candidate table, PV, profile
  cards), round-grouped move log, replay with a step slider.
- `engine/` — live-play adapter: one Playwright Chromium seat per bot
  speaking the site's Socket.IO protocol; every turn re-translates the
  site's authoritative state into a local `GameState` (fixing the old
  round-transition fragility), decides through the same Decision Stack,
  and emits the two-step `chooseTiles`/`placeTiles` protocol.
- `rl/azul_env.py` — PettingZoo AEC environment with action masks
  (the report's chosen standard for future RL training).

## 7. Extending TILES

| To add… | Implement | Register in |
|---|---|---|
| a new Tactician (e.g. RL policy) | `Tactician.decide()` returning a `SearchReport` | `agents/tacticians/__init__.py` |
| a new Profiler (e.g. transformer) | `Profiler.observe/profile/predict` | `agents/profiler/__init__.py` |
| a new Explainer | `Explainer.explain` | `agents/explainer/__init__.py` |
| a new game | a new `core/`-equivalent + translator | session config `mode` |
