# TILES: Milestone 1 Report

**Project:** Multi-Agent Board Game Intelligence Platform  
**Team:** AIS PT07 Group 1  
**Date:** April 2026  
**Status:** Phase 1 Complete, Phase 2 In Progress

---

## 1. Executive Summary

TILES is an AI-driven platform that automates gameplay on the board game Azul, enabling Machine Learning agents to compete, observe, and profile player behavior. The platform bridges the gap between a live web-based game (buddyboardgames.com) and custom ML models, creating an end-to-end pipeline for game intelligence research.

**In the first milestone we delivered a working prototype** that can:
- Launch multiple independent AI agents that play complete Azul games (2-4 players, 5 rounds) on the live platform; recorded games are in `docs/evidence/`
- Record every move with the board state before the move, the scores, timings and the model's top alternatives
- Analyze player behavior through a pluggable profiling framework, including a learned play-style classifier
- Visualize games in real time and provide post-game review of the move log

The platform is built on a modern, extensible architecture (React + FastAPI + Playwright + SQLite) with 438 automated backend tests (plus 13 frontend tests) (rules, game engine, ML players, archetype pipeline, API, parsers, game-over detection) plus one manual live end-to-end test. Measured results are in [EVALUATION.md](EVALUATION.md).

---

## 2. Problem Statement

Board games like Azul present rich decision spaces that combine short-term tactical play with long-term strategic planning. Understanding how different players approach these decisions — their preferences, risk tolerance, and adaptation patterns — is valuable for:

- **AI research**: Training adaptive agents that respond to opponent behavior
- **Player modeling**: Building behavioral profiles that predict future moves
- **Game analytics**: Quantifying play styles and identifying winning strategies

However, no existing platform connects a live game environment to a modular ML pipeline where agents can play, observe, and learn. TILES solves this by providing:

1. **A Play Engine** that interfaces with the real game platform via browser automation
2. **A modular ML framework** where players and profilers are pluggable components
3. **A data pipeline** that captures every game state for training and analysis
4. **A visualization layer** for real-time monitoring and post-game review

---

## 3. Architecture & Technical Design

### 3.1 System Architecture

```
  React Frontend (Vite + Tailwind)          Python Backend (FastAPI)
  ┌─────────────────────────────┐          ┌──────────────────────────────┐
  │ Session Config               │ ◄──────► │ Session Manager               │
  │ Game Monitor (live + replay) │  HTTP/WS │ Play Engine (Playwright)     │
  │ Profile Analyzer             │          │ ML Model Router              │
  └─────────────────────────────┘          │ Profiler Router              │
                                           └──────────┬───────────────────┘
                                                      │ Socket.IO
                                           ┌──────────┴───────────────────┐
                                           │ buddyboardgames.com/azul     │
                                           └──────────────────────────────┘
                                           ┌──────────────────────────────┐
                                           │ SQLite (moves, states, profiles) │
                                           └──────────────────────────────┘
```

### 3.2 Key Technical Decisions

| Decision | Rationale |
|---|---|
| **Socket.IO interception** over DOM scraping | The platform sends authoritative game state via WebSocket. Intercepting this is faster, more reliable, and less brittle than parsing CSS classes. |
| **Multi-browser orchestration** | Each bot runs in its own Chromium instance, joining the same room. This accurately simulates real multiplayer and avoids single-player limitations. |
| **Append-only move ledger** | Every move is recorded with the board state *before* it, the scores before it, timings, and the model's top alternatives. The application never updates or deletes moves (the database does not enforce this). This gives a dataset for training and for step-by-step review. |
| **Pluggable ML interfaces** | Abstract base classes (`MachinePlayer`, `ProfilerAgent`, `ProfileAnalyzer`) allow swapping models without changing the engine. |

### 3.3 Codebase Summary

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy, Playwright, numpy, scikit-learn |
| Frontend | React 19, TypeScript, Tailwind, Zustand |
| Tests | pytest, FastAPI TestClient |

- **15 API endpoints** (REST + WebSocket)
- **438 automated backend tests (plus 13 frontend tests)** (`python -m pytest`; about 96% line coverage of `tiles/`)
- **5 database tables** (sessions, game_states, moves, player_profiles, ml_models). `player_profiles` and `ml_models` are defined but not yet used.

---

## 4. What Has Been Delivered (Phase 1)

### 4.1 Azul Rules Engine
A complete implementation of Azul's game rules including:
- Legal move generation for any board state
- Wall pattern validation (5x5 shifted color grid)
- Tile placement scoring (horizontal + vertical adjacency)
- Floor penalty calculation (-1, -1, -2, -2, -2, -3, -3)
- End-game bonus computation (complete rows +2, columns +7, colors +10)
- Game-over detection (triggered when any player completes a wall row)

Legality and scoring live in `rules.py`; state transitions (applying a move, round scoring, tile recycling) live in `game.py`, which also runs full simulated games. **Validated by 34 rules tests plus 8 game-engine tests**, including an invariant that all 100 tiles are accounted for after every move of full 2-, 3- and 4-player games.

### 4.2 Play Engine (Browser Automation)
The engine launches real Chromium browsers via Playwright and connects to the Azul platform:
- Captures the Socket.IO socket reference via JavaScript injection at page load
- Emits `chooseTiles` and `placeTiles` events directly via the game's protocol
- Waits for server acknowledgment before confirming each move
- Falls back to floor placement if the server rejects a pattern line (stale state recovery); the ledger records the move actually played and flags it (`fell_back_to_floor`)
- Rejects any move the rules engine does not consider legal before executing it
- Supports 2-4 simultaneous bot browsers in the same room
- Configurable headless/headed mode for debugging vs. performance

### 4.3 Machine Players

**GreedyPlayer** — A heuristic scoring engine that evaluates every legal action based on:
- Immediate wall placement points (3x weight for completing pattern lines)
- Pattern line fill progress (preference for near-complete rows)
- End-game bonus potential (row, column, and color set completion)
- Floor overflow penalties
- First-player token cost-benefit analysis

In seeded simulation (200 games, both seats, same deals) GreedyPlayer **wins 100% of games against RandomPlayer (95% CI 98.1-100%)** with a mean score of 59.7 vs 0.8 (`scripts/tournament.py`). Four further style variants (colour-collector, rusher, reckless, blocker) use the same engine with different weights.

**RolloutPlayer** (lookahead) shortlists the heuristic's best moves and simulates the rest of the round for each. In 100 seeded games it wins 98% against GreedyPlayer (95% CI 93-99.4%), 73.2 vs 42.3 points; live it plays at about 0.3 s per move. Counting the opponent's score at full weight made two such players wreck each other (about 16 points each); an opponent weight of 0.4 fixes that without losing strength.

**AdaptivePlayer** observes opponent moves, classifies their style, and switches to the weights that did best against that style in simulation. On unseen deals its mean win rate against the five styles is 0.651 vs 0.604 for the static baseline (+4.7 points), concentrated against the reckless style; against the balanced and blocker styles the difference is not measurable. Full tables and caveats: [EVALUATION.md](EVALUATION.md).

**RandomPlayer** — Uniform random baseline for comparison and testing.

### 4.4 Game Monitor & Replay Viewer
The web UI provides:
- **Real-time board visualization**: Factories, center pool, pattern lines, wall grid, and floor line — all rendered with accurate tile colors
- **"Why this move"**: each move shows the model's top three options with their heuristic scores (and, for AdaptivePlayer, which opponent style it inferred)
- **Round-grouped move log**: Moves organized by round (round boundaries are inferred from the board) with per-round scoring changes. Scores shown with each move are the scores *before* that move. Playback controls (play/pause/step) are not implemented.
- **Expandable move details**: Click any move to see the full board state at that moment — which factory was picked from, which tiles were chosen, where they were placed
- **Game result banner**: Winner announcement with final scores
- **JSON export**: Download complete game data for external analysis

### 4.5 Profile Analyzer
A pluggable behavioral analysis framework:
- **BasicProfileAnalyzer** applies threshold rules to label play styles (high floor usage, conservative, center-focused, factory-focused, colour-biased)
- Computes color preferences, source/destination splits, timing metrics, and scoring trajectories
- **ArchetypeProfileAnalyzer** adds a learned archetype with class probabilities and the behaviours behind the label. A logistic-regression classifier over 10 behaviour features reaches **55.3% held-out accuracy on five simulated styles (chance 20%)**; unsupervised k-means does not separate the styles (adjusted Rand index 0.04). It is trained on bot-vs-bot simulation only, so labels on human games are hypotheses.
- Generates summaries such as: *"Alice played 35 moves, scoring 21 points. Play style: factory-focused, blue-biased. Archetype: RecklessPlayer (62% confidence) because high: overfills lines and spills to the floor."* (illustrative format)
- Profiles are computed on demand after a game; the live game loop feeds opponent moves to adaptive players but does not update the UI in real time
- New analyzers can be registered without modifying core code

### 4.6 Data Export
Every completed game can be exported as a JSON document containing:
- Session metadata (room, players, configuration)
- Per-round score summaries
- Every move with action details, timing breakdown, and full board snapshot
- Documented schema ([EXPORT_FORMAT.md](../backend/EXPORT_FORMAT.md))

---

## 5. What Is In Progress (Phase 2)

| Feature | Status | Description |
|---|---|---|
| **Round transition handling** | Done | Rounds are driven by the platform's own round state (`roundInProgress`) plus an empty-board check, with a deal cool-down because the page also auto-deals. Verified over 7 consecutive live games (5 rounds each); recorded in `docs/evidence/`. |
| **Human-bot mixed games** | Roster logic done; not tested live with a human | Join links are generated and displayed. Bots wait for humans in the lobby. Needs end-to-end validation with real human players. |
| **Game-over detection** | Done | Derived from the platform's state (round finished and a wall row complete); text signals alone are not trusted (an early run was marked "completed" after 29 moves). A session is `completed` only if the final board shows a finished wall row. Confirmed on live games. |
| **DOM state parser accuracy** | 75% | Pattern line state occasionally reads stale data after animations. Floor fallback mechanism compensates, but proper animation-wait logic would be more robust. |

---

## 6. Future Roadmap: AI-Powered Features

The modular architecture is specifically designed to enable the following advanced capabilities:

### 6.0 Status of the proposal items

All items from the original proposal and this roadmap are now implemented (see [FEATURE_STATUS.md](FEATURE_STATUS.md) and [EVALUATION.md](EVALUATION.md)): rulebook ingestion with a benchmark, minimax and MCTS players with profiler conditioning, a Transformer sequence profiler, an opponent next-move model, reinforcement learning (TD(0)), natural-language rationales and commentary, a replay viewer with playback controls, MLflow tracking, an Elo tournament system with genetic-algorithm tuning, external-model integration, and Docker deployment. What remains needs people: running the human-centred explanation study, and trying human players joining through the room link. Sections 6.1-6.6 below are the original roadmap text, kept for reference.

### 6.1 Reinforcement Learning Player
Train a neural network player using the recorded game data:
- **State representation**: Board snapshot → tensor encoding
- **Action space**: Legal moves as discrete choices
- **Reward signal**: Points gained minus floor penalties
- **Training data**: Thousands of GreedyPlayer vs. GreedyPlayer games already producible via simulation

The `MachinePlayer` interface means a trained RL model drops in as a replacement for `GreedyPlayer` with zero engine changes.

### 6.2 Monte Carlo Tree Search (MCTS) Player
Implement an MCTS-based player that:
- Simulates possible futures from the current board state
- Evaluates positions using the existing scoring functions
- Handles the stochastic tile-bag element through random playouts
- Provides configurable search depth/time budget

### 6.3 Opponent Modeling & Adaptive Play
The profiling framework enables a **unified player-profiler agent** that:
- Builds a real-time behavioral model of the opponent during gameplay
- Predicts which tiles the opponent will pick next
- Adapts its strategy dynamically (e.g., blocking preferred colors, competing for the same factory)
- Tests hypotheses by making exploratory moves ("if I take blue, will they switch to red?")

This is the core vision of TILES — agents that don't just play well, but play *differently* based on who they're facing.

### 6.4 Natural Language Game Commentary
Using large language models, generate real-time commentary:
- *"Alice is building toward a complete second row — if she picks up two more reds, that's a 7-point column bonus."*
- *"Bob just sent 3 tiles to the floor. That's a -4 penalty — aggressive move to deny Alice the yellows."*

The board snapshot data structure is already rich enough to serve as context for an LLM.

### 6.5 Multi-Game Tournament System
Run automated tournaments:
- Round-robin brackets with multiple ML models
- Elo rating tracking across games
- Statistical analysis of win rates, score distributions, and matchup advantages
- Automated parameter tuning (genetic algorithms on GreedyPlayer weights)

### 6.6 Transfer to Other Games
The architecture separates game-specific logic (rules, selectors) from platform-generic logic (browser management, state recording, ML interfaces). Supporting a new game requires:
1. New rules engine (legal moves, scoring)
2. New state parser (DOM/Socket.IO mapping)
3. New action executor (click/emit sequences)

The ML framework, database, frontend visualization, and profiling pipeline remain unchanged.

---

## 7. Risk Assessment & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Platform changes (CSS/JS updates) | High | Socket.IO protocol is more stable than DOM. Exploration script can re-map selectors quickly. |
| Rate limiting or blocking | Medium | Headless mode + reasonable play speed. Configurable delays between moves. |
| Browser automation brittleness | Medium | Floor-placement fallback, move verification, configurable timeout+abort. |
| Scalability for tournaments | Low | SQLite sufficient for single-server. Can migrate to PostgreSQL when needed. |

---

## 8. Conclusion

TILES has reached a solid MVP state with a working end-to-end pipeline: AI agents autonomously play Azul, every move is recorded with full board state, and player behavior can be analyzed through pluggable profilers. The architecture is deliberately modular — new ML models, new analyzers, and even new games can be added without restructuring the core platform.

The next phase focuses on hardening the play engine for multi-round games, expanding the ML model library, and demonstrating the platform's unique value: **agents that understand their opponents, not just the game.**

---

*Report prepared by AIS PT07 Group 1 | Repository: [GitHub](https://github.com/rongrongrr/AIS_PT07-Group1_MultiAgentBoardGameIntelligence)*
