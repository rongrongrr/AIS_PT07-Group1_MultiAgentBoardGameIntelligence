# Merge notes: `bugfixes` + `origin/feature/stage2`

Two lines of work diverged from the same early commit. `feature/stage2` rebuilt the project as a `tiles` package around a bit-packed core engine and a four-role Decision Stack; `bugfixes` hardened live play against the real site and added the evaluated ML components, evidence and docs. This file records, area by area, what was kept and why. The rule was "keep the better implementation, whichever branch it came from".

## Decisions

| Area | Kept | Why |
|---|---|---|
| Package name | `tiles` (from stage2); our `app/` moved to `tiles/` | The project is named TILES; one package instead of two. All imports, scripts, tests, Dockerfile and docs updated. |
| Live play (`engine/`) | **Ours** (`tiles/engine/`, `tiles/routers/sessions.py`) | Stage2's adapter (`browser_seat`, `live_session`, `protocol`, `state_translator`) parses Socket.IO `42[...]` frames and an older state shape (`wall.grid`, `currentPlayer`). buddyboardgames.com now sends JSON `{type, payload}` over a plain WebSocket, so that adapter cannot connect. Ours is verified by consecutive live 2-4 player games, locally and in Docker (including after this merge). Dropped, not ported. |
| API server | **Ours** (`tiles/main.py`, `routers/`) | A superset: sessions, WebSocket stream, players, remote models, history, export, state snapshots, profiler analyzers, feedback. Stage2's `server/app.py` offered a subset, tied to the dropped live adapter. `tiles serve` now starts ours. |
| Frontend | **Ours** | Wired to our API and has Replay playback controls, profile analysis, rating widget and Vitest tests (9 pass); stage2's UI targets its own API. |
| Docker | **Ours** (two services: backend + nginx frontend, MLflow profile) | Already proven end to end with live games. Stage2's single-container image depended on its live adapter. CI was taken from stage2 and rewritten for this layout. |
| Rules engine | **Both**, joined by `tiles/bridge.py` | `tiles/core` is a clean, fast engine (bit-packed, 300-slot action space, predicate-level validator) that search and RL need; `tiles/azul` is what the live runtime has been verified with. `tests/test_bridge.py` plays random 2-4 player games through both and asserts identical legal moves every turn and identical scores after every round and at game end. They agree. |
| Search tacticians | **Both**, exposed in one registry | Stage2's PUCT MCTS (with profiler-predicted opponent priors) and paranoid minimax are now live players (`TilesMCTS`, `TilesProfiledMCTS`, `TilesMinimax`) via the bridge. Strength was measured head to head (EVALUATION.md section 18). |
| Profiling | **Both** | Stage2: rule-based archetypes + softmax next-move predictor (feeds `TilesProfiledMCTS`). Ours: logistic regression + Transformer sequence profiler + opponent-style posterior. They answer different questions and are both used. |
| Rule ingestion | **Both** | `tiles/rulebook` (19 specs verified against the core engine; `tiles verify-rules`) and `tiles/rules_ingest` (retrieval, extraction, benchmark on unseen phrasings, validator configuration). |
| Ledger, telemetry, turn pipeline, tournament / ablation / prediction-eval, PettingZoo env, CLI | **Stage2** (adopted as is) | We had nothing equivalent. `tiles` CLI commands run offline; tests added for the CLI and trackers. |
| Explainer | **Both** | Ours (`tiles/explain`) drives the live UI rationales and is faithfulness-verified by simulation; stage2's (`agents/explainer`) explains core-engine decisions. |
| Tests | Both suites kept | Stage2's tests are in `tests/test_core_*.py`; tests for its dropped live adapter and server were removed. |
| Docs | Merged | README, ARCHITECTURE, API rewritten for the merged layout; STAGE2_PLAN kept with a note; our evaluation, status, protocol and evidence kept. |

## Not carried over

`tiles/engine/{browser_seat,live_session,protocol,state_translator}.py` and `tiles/server/app.py` from stage2, with their tests (`test_server`, `test_state_translator`), the root `Dockerfile` / `Dockerfile.live`, `start.sh` and the rewritten frontend. Reasons are in the table above.
