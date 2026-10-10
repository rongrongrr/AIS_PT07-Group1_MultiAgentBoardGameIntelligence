# TILES — Stage 2 Plan (Final Report & Completion)

The progress report committed to: a functional multi-agent prototype, a rule
extraction module with an accuracy benchmark, an opponent modeling module
with predictive-accuracy evaluation against baselines, an opponent profiling
module with 3–5 archetypes, an explainability dashboard, and final
deliverables of a documented source repository, a technical report, and a
demo. This document lays out exactly what remains, how to produce every
number the final report needs, and a proposed report outline.

## 0. Where we are after the rebuild

| Feature (from the progress-report table) | Stage-1 status | Now |
|---|---|---|
| Game state representation | Initial dev done | **Done** — dual representation (bit-packed engine state + JSON view), 300-slot action space |
| Deterministic Validator | Initial dev done | **Done** — predicate-level violations, audit trail, reject/retry loop in the orchestrator |
| Tactician (heuristic) | Initial dev done | **Done** — decomposed weighted heuristic (XAI-ready) |
| Tactician (search: MCTS/minimax + profiler conditioning) | Planned | **Done** — paranoid minimax; PUCT MCTS with profiler-predicted opponent priors |
| Profiler (rule-based) | Initial dev done | **Done** — 5 archetypes + trait accumulation |
| Opponent modeling (predictive policy) | Planned | **Done** — Bayesian prior→posterior next-move predictor (88% top-1 in initial eval) |
| Rule ingestion (RAG) | Planned | **Done** — rulebook → RuleSpecs → engine-verified (19/19) |
| Explainability | Partial | **Done** — search-artifact rationales + concept tags + XAI panel in the UI; LLM refinement optional |
| Game telemetry / ledger / replay | Initial dev done | **Done** — append-only ledger, WS telemetry, replay view |
| Multi-agent orchestration | Initial dev done | **Done** (local); live adapter ported, needs live validation |
| Experiment tracking (MLflow) | Planned | **Done** — MLflow-or-JSONL tracker wired into ablation/tournament |
| Containerization | — | **Done** — `Dockerfile`, `Dockerfile.live`, `docker-compose.yml` |

What remains is **evidence, validation, and writing** — plus optional stretch
items. Four workstreams:

---

## Workstream A — Experiments (the numbers the final report needs)

Each experiment has a ready-made command; budget a machine-day total.
Record everything through MLflow (`docker compose --profile telemetry up`,
`export MLFLOW_TRACKING_URI=http://localhost:5000`) so the report can show
tracked runs.

**A1. Profiler ablation (headline result).**
`tiles ablate --games 50 --simulations 400 --tracker mlflow`
Conditions: greedy → mcts → mcts_profiled vs a fixed blocker opponent.
Report: win rate ± CI, average score margin, decision latency overhead of
profiling. *This is the report's core claim (adaptive play works) — if
mcts_profiled ≤ mcts at n=50, tune the prior-blend ratio (0.7) and the
predictor temperature before concluding; the 4-game smoke run is noise.*

**A2. Opponent-model prediction accuracy.**
`tiles predict-eval --games 30` — top-1/top-3 vs uniform and static-greedy
baselines, split by early/mid/late game to show the cold-start
prior→posterior transition. Extend `prediction_eval.py` to also evaluate
against *human* moves once live games exist (the ledger already records
everything needed).

**A3. Tactician strength ladder.**
`tiles tournament --games-per-pair 10 --simulations 400 --output results.json`
Elo table for random/greedy/minimax/mcts/mcts_profiled; add a
simulations-budget sweep (100/400/1000) for the MCTS strength-vs-latency
curve.

**A4. Archetype discovery.**
Generate ~100 games with varied greedy weight presets (blocker, collector,
risk-taker, cautious, vanilla), fit the pure-Python k-means (k=5) on the
trait vectors, and report cluster–preset agreement plus the rule-based
classifier's confusion matrix. Deliverable: "3–5 distinct archetypes,
recovered unsupervised." (Small script over `tiles.agents.profiler`; ~50
lines, lives in `sim/`.)

**A5. Rule-extraction benchmark.**
`tiles verify-rules` (deterministic path: 19/19 = 100%). With an
`ANTHROPIC_API_KEY`, also run `extract_rules_llm` and report its accuracy
vs the deterministic extractor — a genuinely interesting LLM-vs-symbolic
comparison for the report.

**A6. XAI human evaluation.**
The scope commits to "human-centered evaluation." Cheapest credible
version: 5–10 participants see ~10 moves each with the XAI panel and rate
explanations on clarity / faithfulness / usefulness (Likert 1–5), with a
few distractor explanations (swapped from other moves) to test whether
faithful explanations are distinguishable. One evening of data collection;
strong report section.

**A7. Latency telemetry.**
Per-node timing (decide/validate/explain) distributions straight from the
ledger's TurnRecords — supports the report's "orchestrated under latency
considerations" claim. Include the MCTS 300-sims ≈ 200 ms figure.

## Workstream B — Live-platform validation & demo

1. `pip install -e '.[live]' && playwright install chromium` (or
   `docker compose --profile live up`), then run one bot-vs-bot live game
   headed. Validate, in order: join/lobby selectors, socket capture,
   two-step `chooseTiles`/`placeTiles` acks, `dealTiles` at round
   boundaries, game-over signals. Fix drift in `tiles/engine/browser_seat.py`
   (all site specifics are isolated there and in `protocol.py`).
2. One mixed human-vs-bot live game (a teammate joins via the room link) —
   this also produces the human data for A2.
3. Record the demo video: create session in UI → live monitor with XAI
   panel → mcts_profiled adapting to a blocker → replay view → export.
   Script the narration around the four agents.

## Workstream C — Packaging & repo hygiene

- Push this repo to the team GitHub (replace or archive the old repo).
- CI is included (`.github/workflows/ci.yml`: backend tests, frontend
  build, Docker build) — verify it goes green on GitHub.
- Tag `v1.0` once A1–A5 are in.

## Workstream D — Stretch (only if time allows; all interfaces are ready)

- **RL Tactician**: PPO over `tiles/rl/azul_env.py` (action-masked
  PettingZoo env is tested); drops in via the `Tactician` registry.
- **Transformer/sequence Profiler**: replace `predictor.py`'s
  component-weight policy behind the same `Profiler` interface.
- **LLM live commentary**: the `llm` explainer already does per-move
  commentary; a session-level commentator is a small addition.
- **LangGraph port**: `orchestration/turn_graph.py` is a deterministic
  node graph by design; porting to LangGraph is mechanical if the report
  wants the framework name on the diagram.

## Final report outline (maps sections → evidence)

1. Introduction & problem statement — reuse stage-1 text.
2. System architecture — `docs/ARCHITECTURE.md` + the four-agent diagram;
   emphasize the engine-inversion redesign and why.
3. Rule ingestion — pipeline diagram; **A5** table.
4. Opponent modeling & profiling — method (prior→posterior), **A2**
   accuracy tables, **A4** clusters.
5. Strategic search — PUCT + opponent-prior injection; **A3** Elo ladder,
   sims-vs-strength curve.
6. Explainability — template pipeline + examples; **A6** human eval.
7. Evaluation — **A1** ablation as the headline; **A7** latency.
8. Live deployment — Workstream B results, screenshots, demo link.
9. Engineering — tests (79 green), containerization, CI, ledger/replay.
10. Limitations & future work — Workstream D + known gaps (archetype
    confidence ~0.4 on competent play; live-site brittleness).

## Suggested split (5 members, ~4–6 weeks)

| Owner | Workstream |
|---|---|
| 1 | A1 + A3 + A7 (experiments at scale, MLflow) |
| 2 | A2 + A4 (opponent modeling & archetype analysis) |
| 3 | B (live validation, human games, demo video) |
| 4 | A5 + A6 (LLM extraction comparison, human XAI study) |
| 5 | C + report assembly & editing |
