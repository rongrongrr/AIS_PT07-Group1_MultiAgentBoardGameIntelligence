# Feature status (final submission)

Every feature in the progress report's implementation table, plus the deliverables, scope items and roadmap items, with what exists, how it was verified, and what "done" does *not* cover. Numbers come from [EVALUATION.md](EVALUATION.md).

## Progress-report table

| # | Feature (proposal scope) | Report said | **Now** | What exists | Verified by | Caveats |
|---|---|---|---|---|---|---|
| 1 | Game state representation | Done | **Done** | `GameStateData` / `PlayerState` Pydantic models; ledger-format records and converters (`state_from_record`) | unit tests, live games | n/a |
| 2 | Deterministic Validator | Done | **Done** | `azul/rules.py` (legality, scoring, bonuses), `azul/game.py` (state transitions), validator gate before every executed move, `RulesConfig` driven by ingested rules | rules + engine tests (tile conservation over full 2-4 player games); live runs | the coordinator role lives in the session orchestrator, not the rules module |
| 3 | Tactician (heuristic) | Done | **Done** | `GreedyPlayer` + 4 style variants; GA-tuned weights; TD-learned value player | tournaments, Elo | GA gain is modest (62% vs default Greedy) |
| 4 | **Tactician (search): MCTS/Minimax with profiler conditioning** | Planned | **Done** | `MinimaxPlayer` (alpha-beta), `MCTSPlayer` (UCT), `ConditionedMCTSPlayer`, `ConditionedMinimaxPlayer`, `RolloutPlayer`; Elo round robin | Elo 1741 (Minimax), 1738 (MCTS); live games in Docker | conditioning gain is small (+2.7 margin points, MCTS); conditioned Minimax unit-tested, strength not measured |
| 5 | Profiler (rule-based) | Done | **Done** | `BasicProfileAnalyzer` (colour, source, destination, timing, style notes) | API + UI tests | thresholds are heuristic |
| 6 | **Profiler (ML-based): sequence modelling and archetype clustering** | Planned | **Done** | Transformer / GRU sequence profiler (PyTorch) with saliency reasons; logistic-regression archetype classifier; k-means clustering evaluated | held-out accuracy: Transformer 78.0% full game, 68.7% from 5 moves; LR 55-61%; k-means ARI 0.04 (does **not** separate styles) | trained on simulated bot play only; human accuracy unknown |
| 7 | **Opponent modelling (predictive opponent policy)** | Planned | **Done** | `OpponentModel`: style posterior + next-move prediction, used by the conditioned search players | top-1 81-98% on in-library opponents vs ~18% chance; ~55% on out-of-library lookahead players (no better than a fixed heuristic) | does not generalise to lookahead opponents; humans untested |
| 8 | Game state telemetry | Done | **Done** | per-move decision / click / websocket-wait / total ms, legal-move counts, system log over WebSocket | live games; logged to MLflow | n/a |
| 9 | Action trace ledger | Done | **Done** | SQLite ledger: every move with the board before it, scores, timings, alternatives, rationale; JSON export | tests, live games | append-only by convention (not enforced by the database) |
| 10 | Multi-agent orchestration | Done | **Done** | 2-4 Chromium bots per session, host creates room and starts only when the roster is confirmed; Docker deployment | consecutive live games, 2-4 players, local and Docker; recorded in `docs/evidence/` | human slot tested live with an outside scripted browser (not a person); human moves are inferred from the board and recorded |
| 11 | **Visualization and replay** | Done (no playback) | **Done** | live monitor, round-grouped move log, **Replay with play / pause / prev / next / jump / speed / jump-to-round**, winner banner, export | 9 Vitest tests; real-browser check against Docker (`docs/evidence/ui_replay.png`) | n/a |
| 12 | **Explainability (decision explanations tied to search internals)** | Partial | **Done** | top-3 alternatives with scores, **natural-language rationale and commentary** from engine facts (optional LLM rewrite), opponent read, rating widget, text-vs-scores control condition | every claim re-derived by simulating the move, >1,500 positions, all match; 51/51 live moves carried rationales | **human study: instrument and protocol ready, no participant data yet**; LLM rewrite not run live |
| 13 | **Experiment tracking (MLflow)** | Planned | **Done** | automatic logging of every finished game (config, scores, latency, telemetry, ledger); `--mlflow` on the evaluation scripts; optional UI service | tests; verified in Docker | n/a |

## Deliverables

| Deliverable | Status | Evidence |
|---|---|---|
| Functional prototype (agents operate independently, integrate seamlessly) | **Done** | live games 2-4 players; `docker compose up --build` |
| Rule extraction and ingestion module with accuracy benchmark | **Done** (see caveat) | 16/16 on the real corpus; ingested config plays identical games; generated-rulebook benchmark with dev / held-out / fresh phrasing groups. **Honest generalisation estimate: ~63% field accuracy on unseen phrasings** (93% after error analysis, no longer independent). LLM extractor stub-tested only |
| Opponent modelling module: next-move prediction accuracy, comparison with random / greedy / minimax baselines | **Done** | EVALUATION.md sections 8 and 10 |
| Opponent profiling: 3-5 distinct archetypes | **Done** | 5 archetypes, three classifiers |
| Explainability dashboard: why a move was chosen / how a profile was derived | **Done** | rationale + alternatives per move; profile reasons from feature contributions and saliency |
| Source repository with documentation | **Done** | README, EVALUATION, this file, protocol |
| Technical report, demo | for the team | evidence, results and corrections list are in `docs/` |

## Scope items

| Scope item | Status |
|---|---|
| AI / ML / DL: rule extraction, opponent modelling, profiling | **Done** |
| Transformer-based architectures | **Done** (sequence profiler) |
| Reinforcement learning | **Done** (TD(0) value-function player; parity with the heuristic, not better) |
| Probabilistic modelling | **Done** (opponent-style posterior) |
| NLP: rulebook understanding with retrieval | **Done** (TF-IDF retrieval + extraction; LLM extractor stub-tested) |
| Explainable AI: transparent profiling, human-centred evaluation | **Done** except participant data collection |
| Data science: feature engineering, clustering, classification of archetypes | **Done** |
| Systems: modular agent architecture | **Done** (Validator / Tactician / Profiler / Explainer components) |

## Future-roadmap items from the report

| Roadmap item | Status |
|---|---|
| Enhanced MCTS player | **Done** |
| Opponent modelling and adaptive play | **Done** |
| Natural-language game commentary | **Done** (template-based from engine facts; optional LLM rewrite) |
| Multi-game tournament system with Elo and genetic-algorithm tuning | **Done** |

## Additional (PRD) items

| Item | Status |
|---|---|
| External-model API (register an HTTP model as a player; reference action endpoint) | **Done** |
| Profiler ingest / insights endpoints | **Done** (`GET /api/profiler/{id}/insights`, `POST /api/profiler/ingest`, `GET /api/profiler/stream/{id}/insights`); live insights panel in the Game Monitor and a profile overlay in the Replay |
| Authentication | **Done**, optional: set `TILES_API_KEY` to require `X-API-Key` (HTTP) / `?api_key=` (WebSocket); the UI prompts for it. Off by default for local use |
| Human players in a session | **Done**: moves of players outside TILES are inferred from the board and recorded, so profilers and adaptive bots can model them |
| Leaderboard (tournament results in the UI) | **Done**: Leaderboard tab reads `models/elo_results.json` |

## Merged stage-2 components (teammate's `feature/stage2` work)

| Component | Status | Notes |
|---|---|---|
| Core engine, 300-slot action space, predicate-level Validator, PettingZoo env | **Done**, in use | Cross-checked against the live-runtime rules over full games (`tests/test_bridge.py`) |
| PUCT MCTS with profiler priors, paranoid minimax | **Done**, playable live as `TilesMCTS`, `TilesProfiledMCTS`, `TilesMinimax` | Strength measured in EVALUATION.md section 18 |
| Ledger, telemetry, turn pipeline, `tiles` CLI, ablation / prediction-eval | **Done** | Offline simulations only |
| `tiles/rulebook` verifier | **Done** | 19/19 specs verified against the core engine |
| Socket.IO live adapter and its server | **Not kept** | The site no longer speaks Socket.IO; see MERGE_NOTES.md |

## What is still outstanding (needs people, not code)

1. Run the human-centred evaluation with real participants ([protocol](HUMAN_EVALUATION_PROTOCOL.md)) and report its results.
2. Apply [REPORT_CORRECTIONS.md](REPORT_CORRECTIONS.md) to the report PDF and write the technical paper (Phase 2).
3. Individual accomplishment reports (git history is concentrated in one author; document non-code contributions).
4. Identify a sponsor or users for the customer-feedback criterion.
5. Try real people joining through the room link (an outside scripted browser has been tested), and, if an API key is available, run the LLM extractor and explainer.
