# Roadmap: what was considered, what was built, what was not

Every item from the proposal, the progress report's "Future Roadmap" (Milestone report section 6) and the PRD was checked against the code. Status per item is in [FEATURE_STATUS.md](FEATURE_STATUS.md); measured results are in [EVALUATION.md](EVALUATION.md). This file records the *decisions* about the remaining roadmap: whether each idea was worth building, and why.

## Roadmap items from the report

| Item | Decision | Result |
|---|---|---|
| 6.1 Reinforcement-learning player | Built | `TDPlayer` (TD(0) self-play) and the PettingZoo env in `tiles/rl`. Parity with the heuristic (about 47% win rate), not better. See EVALUATION section 12. |
| 6.2 Enhanced MCTS | Built, twice | UCT MCTS (`MCTSPlayer`) and stage-2's PUCT MCTS (`TilesMCTS`); the PUCT version is stronger (EVALUATION section 18). |
| 6.3 Opponent modelling and adaptive play | Built | Style posterior, learned softmax next-move predictor, conditioned search. Gain inside the search is small (+2.7 margin points); measured, reported as such. |
| 6.4 Natural-language commentary | Built | Rationales and commentary from engine facts, faithfulness-verified by simulation; optional LLM rewrite. |
| 6.5 Tournament system (Elo, win-rate matrix, GA tuning) | Built | `scripts/elo_tournament.py`, `tiles tournament`, GA in `tiles/ml/tuning.py`; results are visible in the UI **Leaderboard** tab. |
| 6.6 Transfer to other games | **Not built, on purpose** | See below. |

## PRD items that were still open at the start of the final stage

| Item | Decision |
|---|---|
| `POST /api/profiler/ingest`, `GET /api/profiler/{id}/insights` | Built (with a live insights panel and a replay overlay). They are cheap and they close the gap between "profiles computed on demand" and the PRD's real-time profiler panel. |
| Authentication | Built as an optional shared secret (`TILES_API_KEY`). A real user system is out of scope for a local tool. |
| Human participants in a session | Built: moves of players outside TILES are inferred from the board and recorded, which the profilers need in order to say anything about humans at all. |

## Ideas considered and not built

* **A second game (6.6).** The architecture is split the way the report says (rules, state parser and executor are game-specific; browser management, ledger, ML interfaces and UI are not), and `tiles/core` + `tiles/agents` are already free of any website code. But adding a second game means a second rules engine, a second platform integration with its own failure modes, and a second evaluation, none of which would strengthen the project's claims about Azul profiling, and a half-working second game would weaken them. Cost high, value for the stated objectives low. The extension points are documented in ARCHITECTURE section 7.
* **AlphaZero-style self-play network for the MCTS.** The PettingZoo env makes it possible, but the TD(0) experiment already showed that learning from self-play at this budget only reaches parity with the heuristic, and the search players are already well above it. A network would need far more compute than a student project has, with a high chance of a negative result. Not worth it.
* **Training the profilers on human games.** The most valuable scientific next step, but it needs people (the human-evaluation protocol and the room-link study), not code. The tooling is ready: human moves are recorded, `scripts/analyze_feedback.py` analyses ratings, the protocol is in [HUMAN_EVALUATION_PROTOCOL.md](HUMAN_EVALUATION_PROTOCOL.md).
* **Running the LLM extractor / explainer.** Implemented against an interface and tested with stubs; running them needs an API key the project did not have. Nothing to build.
* **Distributed or parallel search.** Decisions already take well under the move timeout; parallelism would add complexity without changing results.

## Genuinely outstanding (needs people)

1. Run the human-centred explanation study with real participants and report it honestly, including a null result.
2. Try real people joining through the room link (an outside scripted browser has been tested).
3. Apply the report corrections and write the Phase 2 paper; individual accomplishment reports; a sponsor or user for the customer-feedback criterion.
