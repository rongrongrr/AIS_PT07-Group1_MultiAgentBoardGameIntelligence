# Corrections to the submitted progress report (PDF)

> **Superseded rows:** several rows below describe features as "Planned" or "Partial" or suggest wording for a partly finished system. Those features are now implemented. Use the **final status table at the end of this file** and [FEATURE_STATUS.md](FEATURE_STATUS.md); keep the rest of this list only for the claims it corrects (tests, scores, ledger, architecture roles, citations).

The PDF `AIS_PT07_STK05_Capstone_Group1_FirstGroupReport.pdf` is maintained outside this repo, so these are the edits to make there. "Evidence" points to what supports the replacement text. Page numbers are PDF-viewer pages. Items marked **decide** need a team decision, not just a wording change.

## Statements that the code does not support

| Page / section | Current text | Replace with | Evidence |
|---|---|---|---|
| p.3 Background | "approximately 100-180 possible move combinations, but only 10-15 percent are legally valid... branching factor far larger than Chess (31-35)" | Remove the "far larger than Chess" comparison, or recompute. 100-180 x 10-15% is only 10-27 legal moves, fewer than chess, which contradicts the sentence. Table 1 also omits the floor option and the centre pool. **decide:** measure the real branching factor with `get_legal_actions` over simulated games and cite that. | Arithmetic; `tiles/azul/rules.py` |
| p.3 | "10-15 percent... (Plan B Games, 2017)" | Cite where the percentage actually comes from; the rulebook is unlikely to state it. | n/a |
| p.5 Key Capabilities | "Every move is validated, executed, and persisted with full game-state context. Decisions can be replayed and audited at any time" | "Every move is checked against the rules engine before execution and persisted with the board state before the move, scores, timings, and the model's top alternatives. Replay is a step-through move log; playback controls are not implemented." | `sessions.py` validator gate; no replay controls in frontend |
| p.5 Key Capabilities | "The system continuously learns opponent behavior, classifies play styles using historical data, and dynamically adjusts strategies... adapt in real time" | "A profiler classifies opponent play style from observed moves, and an adaptive player switches strategy accordingly. In simulation this raises mean win rate from 0.604 to 0.651 against five bot styles (see EVALUATION.md). It has not been tested against human players." | `docs/EVALUATION.md` section 4 |
| p.7 Architecture | "The Validator is both the deterministic Azul rules engine and the per-turn coordinator" | The rules engine (`rules.py`, `game.py`) validates moves; turn coordination is done by the session orchestrator (`sessions.py`). Reword the four-role description or the diagram. | `routers/sessions.py` |
| p.7 diagram | `propose(legal, profile)` edge from Validator to players | The Tactician interface is `decide(state, player_index)`; opponent information reaches adaptive players through `observe(record, name)`. Update the arrow labels. | `ml/base.py` |
| p.8 | "Explainer builds the board snapshots, profile summaries, and (planned) natural-language rationales" | There is no Explainer component. Say: board snapshots and per-move top-3 alternatives are stored by the orchestrator and shown by the UI; natural-language rationales are planned. | no Explainer code |
| p.7 | "GreedyPlayer... beats RandomPlayer 43-3" | "GreedyPlayer wins 200 of 200 simulated games against RandomPlayer (95% CI 98.1-100%), mean score 59.7 vs 0.8." (also in the p.12 table) | `python scripts/tournament.py --games 100 --seed 1` |
| p.7 and p.12 | "ledger... full board-state snapshot" / "Immutable move recording" | "Append-only move ledger with the board state before each move." The database does not enforce immutability. | `models/db.py` |
| p.12 table | "47 unit tests" | "333 automated backend tests (plus 9 frontend tests) (34 in the rules engine)" | `python -m pytest` |
| p.12 table, Visualization & Replay | "Initial development done" for "Live monitoring and post-game review" with "winner banner" | Keep, but call it a move log, not replay, and note playback is not built. | frontend |
| p.12 table, Multi-agent orchestration | "Supports 2-4 Chromium browsers per session" | Add: "Multi-round live play has not yet been verified over a recorded full game." | see README, Status |
| p.10-11 Figures 5-6 | Screenshot of a "completed" game with 29 moves and a 2-0 score | Replace with a screenshot of a genuinely finished game, or remove. A finished Azul game needs at least one completed wall row. The earlier game-over detector could fire falsely; it has since been fixed. | `play_engine.py` |
| p.12 table, Profiler (Rule-based) | "BasicProfileAnalyzer with 5 style traits" | "Rule-based analyzer with threshold labels (floor usage, centre/factory focus, colour bias, timing)". The "aggressive (high floor usage)" label is a heuristic, not validated. | `ml/analyzers.py` |
| p.13 table, Profiler (ML-based) | "Planned" | "Initial development done": logistic-regression archetype classifier, 55.3% held-out accuracy vs 20% chance on simulated styles; k-means did not separate the styles. Note it is trained on simulation only. | `docs/EVALUATION.md` section 3 |
| p.13 table, Tactician (Search) / Opponent Modeling | "Planned" | Opponent modelling: **partial**: observed-move classification feeding a best-response switch. MCTS/minimax: still planned. Not a next-move predictor. | `ml/adaptive_player.py` |
| p.12-13 Explainability | "Partial; missing per-action score breakdown UI" | Per-action top-3 scores are now stored and displayed. Still partial: no natural-language rationale and no user evaluation. | `GameMonitor.tsx` |
| p.6 Deliverables | RAG rule extraction, rule-parsing accuracy benchmark, next-move prediction accuracy, minimax baseline, human-centred XAI evaluation | Either list as future work with dates, or cut from the deliverables. None exist yet. **decide** | repo has no such code |

## Citations and boilerplate to fix

- **Reference 10** is credited to "Yau, A. (2026)" but the URL is `github.com/mgsweet/Azul-MCTS-AI`. Use the repository owner's actual name.
- **Reference 1** (an arXiv paper on human-aligned chess) is cited for "Stockfish is the most powerful AI opponent". Cite a source that supports that claim, or reword.
- **Reference 3** points only to `boardgamegeek.com`; give the Azul page and access date.
- **Statement on AI use**: the paragraph mentions "official websites of global and local health and environmental bodies" and "this proposal". That is template text from another document. Rewrite it to describe how this team used AI tools on this project.
- **Page 5** says "exhaustive architectural blueprint... decentralized cohort of specialized agents orchestrated under latency considerations". Describe what is built; the LangGraph, bitboard and PettingZoo design in `docs/Multi-Agent Azul System Design.md` is a design study, not implemented.

## Missing for the Phase 1 "detailed project proposal" (see capstone slides)

Project plan with milestones, team roles, requirements (functional and non-functional), risk register (exists in `Milestone_1_Report.md` section 7 but not in the PDF), evaluation plan with success criteria, any sponsor or user identified, and the data/EDA step. Add at least a short section for each.

## For Phase 2

The technical paper needs a results section: `docs/EVALUATION.md` is a starting point. The Individual Accomplishment Report needs per-person evidence; at present the git history is concentrated in one author, so have each member commit their own work, or document non-code contributions explicitly.

## Update: live-platform evidence now exists

- Replace the Figure 5-6 screenshots with ones from a game recorded in `docs/evidence/` (for example `live_game_2p_rollout_vs_greedy.json`: 52 moves, 5 rounds, final 44-30, verified against the platform's final scores). The old 29-move "completed" game should not be used.
- p.5 and p.7 say integration is "through browser automation with Playwright and **Socket.IO**". The platform now uses plain JSON over a WebSocket; write "Playwright and the platform's WebSocket protocol". Mention that the integration is a third-party dependency that changed once during the project.
- p.12 table, Multi-agent orchestration: change the caveat to "verified over 7 consecutive live games with 2-4 players (docs/evidence/)".
- p.12 table, Tactician (Heuristic): add the lookahead `RolloutPlayer` (98% win rate over 100 simulated games against the heuristic player, 95% CI 93-99.4%).
- State plainly that opponent modelling inside the search gave no measurable benefit (docs/EVALUATION.md section 6). A negative result with the numbers is stronger than leaving it out.
- Human players joining via the room link are still untested live.

## Final implementation status table (replace the table on pp.11-13 with this)

| Feature | Planned scope | Current status | Detail |
|---|---|---|---|
| Game state representation | JSON model for all Azul state variables | Done | `GameStateData` / `PlayerState` Pydantic models (factories, centre, pattern lines, wall, floor, scores, token); ledger-format converters. |
| Deterministic Validator | Authoritative rules engine for state transitions | Done | Rules engine (legality, scoring, bonuses) plus state transitions and full-game simulation; every move is validated before execution; rule parameters can be driven by ingested rulebook text. 34 rules tests; tile conservation verified over full 2-4 player games. |
| Tactician (heuristic) | Greedy / heuristic action selection | Done | `GreedyPlayer` and four play-style variants; genetic-algorithm-tuned weights (62% vs default on unseen deals); TD(0) reinforcement-learning player (parity with the heuristic). |
| Tactician (search) | MCTS / minimax with profiler conditioning | Done | Alpha-beta minimax, UCT MCTS, rollout player, and profiler-conditioned MCTS and minimax. Elo round robin: Minimax 1741, MCTS 1738, Rollout 1681, Blocker 1399, Greedy 1361, Random 1079. Conditioning gain is small (+2.7 margin points). |
| Profiler (rule-based) | Style classification from game features | Done | `BasicProfileAnalyzer`: colour, source, destination, timing, style notes. |
| Profiler (ML-based) | Sequence modelling and archetype clustering | Done | Transformer / GRU sequence profiler (78.0% held-out on the full game, 68.7% from the first 5 moves, chance 20%) with saliency reasons; logistic-regression classifier (55-61%); k-means clustering evaluated and found not to separate the styles (adjusted Rand index 0.04). Trained on simulated play. |
| Opponent modelling | Predictive opponent policy | Done | Style-posterior model predicting the next move: top-1 81-98% for opponents in its style library (chance about 18%); about 55% for lookahead opponents outside the library, no better than a fixed heuristic. Used by the conditioned search players. |
| Game state telemetry | Latency and timing metrics per agent | Done | Per-move decision / click / websocket-wait / total ms; system log over WebSocket; logged to MLflow. |
| Action trace ledger | Immutable move recording | Done | Append-only SQLite ledger with the board before each move, scores, timings, alternatives and rationale; JSON export. (Immutability is by convention, not enforced by the database.) |
| Multi-agent orchestration | Independent agents in a shared game room | Done | 2-4 Chromium bots per session; the host starts only once the platform has confirmed every player; verified over consecutive live games with 2-4 players, locally and in Docker. |
| Visualization and replay | Live monitoring and post-game review | Done | Live monitor, round-grouped move log, winner banner, export, and a Replay view with play / pause / step / jump / speed / jump-to-round controls. |
| Explainability | Decision explanations tied to search internals | Done | Top-3 alternatives with scores, natural-language rationale and commentary built from engine facts (every claim verified by simulating the move over more than 1,500 positions), inferred opponent styles, per-move rating widget. Human-centred study: instrument and protocol ready; participant ratings still to be collected. |
| Experiment tracking | MLflow integration | Done | Every finished game logged automatically with its telemetry; evaluation scripts log with `--mlflow`; optional MLflow UI container. |

Also add to the report: rulebook ingestion (retrieval + extraction + validator configuration; 16/16 on the real corpus, about 63% field accuracy on unseen phrasings in the benchmark), the tournament system with Elo and GA tuning, reinforcement learning, external-model integration, and Docker deployment. State the open items plainly: no human participant data for the explanation study, LLM components tested with stubs only, human players joining via the room link not tested live.
