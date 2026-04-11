# TILES - Product Requirements Document

## 1. Executive Summary

TILES is an AI-driven platform that interfaces with the web-based board game **Azul** (hosted on [buddyboardgames.com](https://buddyboardgames.com/azul)). It acts as a bridge between the game's web UI and custom ML models, enabling automated **Machine Players** to compete and **Profiling Agents** to observe, record, and analyze player behavior to build behavioral profiles.

---

## 2. Objectives

| Objective | Description |
|---|---|
| **Play Engine** | Headless browser automation (Playwright) to parse game states and execute moves via the Azul web UI |
| **Modularity** | Decouple game logic, Machine Players, and Profiling Agents into independent, swappable components |
| **Extensibility** | Expose standardized API endpoints so external developers can plug in custom AI models as players, profilers, or both |
| **Data Integrity** | Maintain an immutable ledger of all game states and player moves in SQLite |

---

## 3. Target Platform Analysis

### 3.1 BuddyBoardGames Azul - Technical Profile

The target platform has the following characteristics (discovered via exploration):

- **Transport**: Socket.IO (WebSocket) — no REST API. All game communication is real-time.
- **Room-based multiplayer**: 2-4 players per room. Rooms are identified by name, shared via URL.
- **Join flow**: Client emits `joinRoom`; if room doesn't exist, falls back to `createRoom` (first player becomes host).
- **Turn protocol** (two-step):
  1. `chooseTiles` — select a color from a factory or center pool
  2. `placeTiles` — place selected tiles onto a pattern line or floor
- **State sync**: Server is source of truth. Every `takeTurnResponse` includes the full `game` state object.
- **Key Socket.IO events**:
  - Client → Server: `createRoom`, `joinRoom`, `startGame`, `takeTurn`, `playAgain`
  - Server → Client: `createRoomResponse`, `joinRoomResponse`, `startGameResponse`, `takeTurnResponse`, `endGameResponse`
- **URL name param**: `?name=<base64>` pre-fills the player name field.
- **Frontend**: jQuery + jQuery UI, LESS CSS, no modern framework.
- **Tile types**: `black`, `blue`, `red`, `white`, `yellow`, `firstPlayer`

### 3.2 Azul Game Rules Summary

- **Setup**: 5 factories (2-player) to 9 factories (4-player), each with 4 random tiles drawn from a bag of 100 tiles (20 per color).
- **Drafting**: On your turn, pick all tiles of one color from a single factory (remaining tiles go to center) OR pick all tiles of one color from the center pool. First to take from center gets the first-player token (and a floor penalty).
- **Placement**: Place drafted tiles onto one of 5 pattern line rows (row N holds N tiles). Excess tiles go to the floor line.
- **Wall Tiling**: When a pattern line row is full at round end, one tile moves to the corresponding wall position. Scoring = count of contiguous horizontal + vertical tiles touching the placed tile (minimum 1).
- **Floor Penalties**: -1, -1, -2, -2, -2, -3, -3 for positions 1-7.
- **End Game Bonus**: +2 per complete horizontal wall row, +7 per complete vertical wall column, +10 for completing all 5 of one color.
- **Game End**: Triggered when any player completes a full horizontal row on their wall. Finish the current round, then score bonuses.

---

## 4. System Architecture

### 4.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   React Frontend (Vite)                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │
│  │  Session      │ │  Game        │ │  Replay          │ │
│  │  Config Page  │ │  Monitor     │ │  Viewer          │ │
│  └──────────────┘ └──────────────┘ └──────────────────┘ │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / WebSocket
┌────────────────────────┴────────────────────────────────┐
│              Python Backend (FastAPI)                     │
│  ┌──────────┐ ┌───────────┐ ┌────────────┐ ┌─────────┐ │
│  │ Session  │ │ Play      │ │ ML Model   │ │ Profiler│ │
│  │ Manager  │ │ Engine    │ │ Router     │ │ Router  │ │
│  └──────────┘ └─────┬─────┘ └────────────┘ └─────────┘ │
│                      │                                   │
│              ┌───────┴────────┐                          │
│              │  Playwright    │                          │
│              │  Browser Pool  │                          │
│              └───────┬────────┘                          │
└──────────────────────┼──────────────────────────────────┘
                       │ Socket.IO
              ┌────────┴─────────┐
              │ buddyboardgames  │
              │   .com/azul      │
              └──────────────────┘

┌─────────────────────────────────────┐
│         SQLite Database             │
│  sessions | game_states | moves |   │
│  profiles | ml_models              │
└─────────────────────────────────────┘
```

### 4.2 Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Frontend** | React 18 + TypeScript + Vite | Modern SPA with fast dev experience |
| **UI Library** | Tailwind CSS + shadcn/ui | Rapid, consistent UI development |
| **State Mgmt** | Zustand | Lightweight, minimal boilerplate |
| **Backend** | Python 3.12 + FastAPI | Async-native, auto-generated OpenAPI docs |
| **WebSocket** | FastAPI WebSocket | Real-time game state push to frontend |
| **Browser Automation** | Playwright (Python) | Chromium (headless or headed) to interact with Azul web UI |
| **Database** | SQLite (via SQLAlchemy) | Zero-config, file-based, sufficient for single-server deployment |
| **Task Queue** | asyncio (built-in) | Manage concurrent browser sessions and ML model calls |
| **ML Interface** | Python ABC + REST | Abstract base class for local models; REST for remote models |

### 4.3 Project Structure

```
tiles/
├── frontend/                    # React app (Vite)
│   ├── src/
│   │   ├── components/
│   │   │   ├── SessionConfig.tsx    # Game session setup
│   │   │   ├── GameMonitor.tsx      # Live game state viewer
│   │   │   ├── ReplayViewer.tsx     # Historical game replay
│   │   │   └── PlayerBoard.tsx      # Azul board visualization
│   │   ├── stores/
│   │   │   └── gameStore.ts         # Zustand state
│   │   ├── api/
│   │   │   └── client.ts            # API + WebSocket client
│   │   ├── App.tsx
│   │   └── main.tsx
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app entry
│   │   ├── routers/
│   │   │   ├── sessions.py          # Session CRUD
│   │   │   ├── players.py           # ML model registration & action
│   │   │   ├── profiler.py          # Profiling agent endpoints
│   │   │   └── history.py           # Game history & replay data
│   │   ├── engine/
│   │   │   ├── play_engine.py       # Playwright orchestrator
│   │   │   ├── state_parser.py      # DOM → GameState JSON
│   │   │   └── action_executor.py   # GameAction → DOM clicks
│   │   ├── models/
│   │   │   ├── db.py                # SQLAlchemy models + SQLite setup
│   │   │   └── schemas.py           # Pydantic schemas
│   │   ├── ml/
│   │   │   ├── base.py              # Abstract MachinePlayer / ProfilerAgent
│   │   │   ├── random_player.py     # Reference: random valid move player
│   │   │   └── registry.py          # Model registration & dispatch
│   │   └── azul/
│   │       ├── rules.py             # Azul rule validation & move legality
│   │       └── scoring.py           # Scoring calculator
│   ├── tests/
│   └── requirements.txt
│
├── db/
│   └── tiles.db             # SQLite database file
│
└── README.md
```

---

## 5. User Interface Requirements

### 5.1 Session Configuration Page

The control panel for setting up and launching automated game sessions.

| Element | Type | Description |
|---|---|---|
| Game Platform URL | Text input | Pre-filled with `https://buddyboardgames.com/azul`, editable |
| Room Name | Text input + auto-generate button | Room identifier for the game session |
| Room URL | Read-only display | Generated after session creation |
| Player Slots (1-4) | Dropdown per slot | Options: `Human`, or any registered Machine Player (e.g., `RandomPlayer`, `ML_Alpha_01`) |
| Profiler Selection | Dropdown | Select a Profiling Agent to observe the session |
| Profiler Targets | Checkboxes | Select which players in the room to profile |
| Browser Mode | Toggle switch | **Headless** (default, no visible browser) or **Headed** (opens a real browser window so users can watch the game live). Headed mode is useful for debugging, demos, and visual verification. |
| Start Session | Button | Launches Playwright browsers, joins room, starts game |
| Session Status | Live indicator | Shows: `Idle` → `Connecting` → `In Lobby` → `Playing` → `Completed` |

### 5.2 Game Monitor Page

Real-time view of the active game session.

- **Visual Board State**: Rendered Azul board for each player (factories, center pool, pattern lines, wall, floor, scores)
- **Move Log**: Scrollable feed of actions taken, with timestamps and decision times
- **Current Turn Indicator**: Highlights whose turn it is
- **Profiler Insights Panel**: Sidebar showing real-time observations from the active Profiling Agent

### 5.3 Game Replay Page

Reconstruct and review past games from the SQLite ledger.

- **Playback Controls**: Play, Pause, Step Forward, Step Back, Jump to Turn N
- **Board Reconstruction**: Renders board state at any point in the game
- **Move Overlay**: Highlight the action taken on each step
- **Profile Overlay**: Display profiler annotations alongside moves

---

## 6. Functional Requirements

### 6.1 Play Engine (Playwright Integration)

The Play Engine manages Chromium browser instances that connect to buddyboardgames.com as Socket.IO clients. Browsers can run in **headless** mode (no UI, faster, lower resource usage) or **headed** mode (visible browser window for live viewing).

**State Retrieval**:
- Launch browser (headless or headed per session config), navigate to Azul room URL
- Intercept Socket.IO `takeTurnResponse` events to capture the authoritative `game` state object directly (preferred over DOM scraping)
- Fallback: Parse DOM elements for factories, center pool, player boards, pattern lines, wall, floor lines, scores
- Translate into structured `GameState` JSON

**Action Execution**:
- Translate `GameAction` JSON into Playwright UI interactions:
  1. Click the target tile color on the target factory/center (triggers `chooseTiles`)
  2. Click the target pattern line row or floor (triggers `placeTiles`)
- Validate actions against Azul rules before execution

**Session Lifecycle**:
- Create/join room → wait in lobby → start game → play turns → detect game end → optionally rematch
- Handle reconnection with exponential backoff (matching platform behavior)

### 6.2 Machine Player Interface

```python
class MachinePlayer(ABC):
    """Abstract base class for all Machine Players."""

    @abstractmethod
    async def decide(self, game_state: GameState) -> GameAction:
        """Given the current game state, return the action to take."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this player model."""
        ...
```

**Interaction flow**:
1. Play Engine pushes `GameState` to the assigned Machine Player when it's their turn
2. Machine Player computes and returns a `GameAction`
3. Play Engine validates the action, then executes it via Playwright
4. Result is logged to SQLite

### 6.3 Profiling Agent Interface

```python
class ProfilerAgent(ABC):
    """Abstract base class for all Profiling Agents."""

    @abstractmethod
    async def observe(self, move_record: MoveRecord) -> ProfileInsight | None:
        """Observe a move and optionally return an insight."""
        ...

    @abstractmethod
    async def summarize(self, session_id: str) -> PlayerProfile:
        """Generate a behavioral profile summary for a player."""
        ...
```

**Capabilities**:
- Receives real-time move notifications via the `observe()` method
- Can access full move history via the history API
- Unified model support: a single class can implement both `MachinePlayer` and `ProfilerAgent` to enable adaptive play strategies

### 6.4 Game Ledger (SQLite)

Every action is recorded as an immutable log entry.

**Recorded data points per move**:
- `session_id`: Links to the game session
- `step_id`: Sequential move number
- `player_name`: Display name in the game
- `system_tag`: Model identifier (e.g., `ML_Alpha_01`)
- `action`: Source (factory/center), color, destination (pattern line/floor)
- `game_state_before`: Full JSON snapshot before the move
- `game_state_after`: Full JSON snapshot after the move
- `decision_time_ms`: Time taken by the Machine Player to decide
- `timestamp`: UTC timestamp

---

## 7. API Endpoints

### 7.1 REST API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/sessions` | Create a new game session with player/profiler config |
| `GET` | `/api/sessions` | List all sessions |
| `GET` | `/api/sessions/{id}` | Get session details and status |
| `POST` | `/api/sessions/{id}/start` | Start the game session |
| `POST` | `/api/sessions/{id}/stop` | Stop/abort a running session |
| `GET` | `/api/history/{session_id}` | Full move log for a session |
| `GET` | `/api/history/{session_id}/state/{step}` | Game state at a specific step |
| `POST` | `/api/players/register` | Register a new Machine Player model |
| `GET` | `/api/players` | List registered Machine Players |
| `POST` | `/api/player/action` | External model endpoint: receive state, return action |
| `POST` | `/api/profiler/ingest` | Push a move record to an external Profiling Agent |
| `GET` | `/api/profiler/{session_id}/insights` | Get profiler insights for a session |

### 7.2 WebSocket API

| Channel | Direction | Description |
|---|---|---|
| `/ws/session/{id}` | Server → Client | Real-time game state updates, move notifications, status changes |
| `/ws/session/{id}` | Client → Server | Manual intervention commands (pause, override move) |

---

## 8. Data Models

### 8.1 GameState

```json
{
  "timestamp": "2026-04-05T15:38:37Z",
  "session_id": "sess_abc123",
  "room_name": "fun-1",
  "round": 3,
  "current_turn": "player_2",
  "factories": [
    ["blue", "blue", "red", "yellow"],
    ["black", "black", "white", "blue"],
    ["red", "yellow", "yellow", "white"],
    ["blue", "red", "black", "black"],
    ["white", "white", "yellow", "red"]
  ],
  "center_pool": ["red", "yellow", "white", "firstPlayer"],
  "players": [
    {
      "index": 0,
      "name": "Human_Alice",
      "system_tag": null,
      "score": 14,
      "pattern_lines": [
        [],
        ["blue"],
        ["red", "red", "red"],
        [],
        ["yellow"]
      ],
      "wall": [
        [false, false, true,  false, false],
        [false, false, false, true,  false],
        [true,  false, false, false, false],
        [false, false, false, false, false],
        [false, false, false, false, false]
      ],
      "floor_line": ["blue"],
      "has_first_player_token": false
    },
    {
      "index": 1,
      "name": "Agent_Bot_V1",
      "system_tag": "ML_Alpha_01",
      "score": 18,
      "pattern_lines": [
        ["white"],
        ["black", "black"],
        [],
        ["red", "red"],
        []
      ],
      "wall": [
        [false, true,  false, false, false],
        [false, false, false, false, true ],
        [false, false, true,  false, false],
        [false, false, false, false, false],
        [false, false, false, false, false]
      ],
      "floor_line": [],
      "has_first_player_token": true
    }
  ]
}
```

### 8.2 GameAction

```json
{
  "source_type": "factory",
  "source_index": 2,
  "color": "red",
  "destination": "pattern_line",
  "destination_row": 3
}
```

Alternative (floor placement):
```json
{
  "source_type": "center",
  "source_index": null,
  "color": "yellow",
  "destination": "floor"
}
```

### 8.3 MoveRecord

```json
{
  "session_id": "sess_abc123",
  "step_id": 42,
  "player_name": "Agent_Bot_V1",
  "system_tag": "ML_Alpha_01",
  "action": {
    "source_type": "factory",
    "source_index": 2,
    "color": "red",
    "destination": "pattern_line",
    "destination_row": 3
  },
  "game_state_before": { "..." : "..." },
  "game_state_after": { "..." : "..." },
  "decision_time_ms": 1450,
  "timestamp": "2026-04-05T15:39:12Z"
}
```

---

## 9. SQLite Database Schema

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,
    room_name       TEXT NOT NULL,
    platform_url    TEXT NOT NULL DEFAULT 'https://buddyboardgames.com/azul',
    status          TEXT NOT NULL DEFAULT 'created',  -- created|lobby|playing|completed|aborted
    browser_mode    TEXT NOT NULL DEFAULT 'headless',  -- 'headless' or 'headed'
    player_config   TEXT NOT NULL,  -- JSON: player slot assignments
    profiler_config TEXT,           -- JSON: profiler assignment + targets
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE game_states (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    step_id         INTEGER NOT NULL,
    state_json      TEXT NOT NULL,  -- Full GameState JSON
    captured_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, step_id)
);

CREATE TABLE moves (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    step_id         INTEGER NOT NULL,
    player_name     TEXT NOT NULL,
    system_tag      TEXT,
    action_json     TEXT NOT NULL,  -- GameAction JSON
    decision_time_ms INTEGER,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, step_id)
);

CREATE TABLE player_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    player_name     TEXT NOT NULL,
    profiler_tag    TEXT NOT NULL,
    profile_json    TEXT NOT NULL,  -- PlayerProfile JSON
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE ml_models (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    model_type      TEXT NOT NULL,  -- 'player' | 'profiler' | 'unified'
    config_json     TEXT,           -- Model-specific configuration
    registered_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## 10. Implementation Phases

### Phase 1: Foundation (Play Engine + Basic UI)

1. **Playwright Exploration Script**: Connect to Azul, intercept Socket.IO events, parse game state into `GameState` JSON
2. **Action Executor**: Translate `GameAction` into Playwright clicks (chooseTiles → placeTiles)
3. **Random Player**: Reference implementation that picks a random valid move
4. **SQLite Ledger**: Record all states and moves
5. **Minimal React UI**: Session config page with room setup + start button

### Phase 2: Full Platform

6. **Game Monitor**: Real-time board visualization in React
7. **Multiple Browser Sessions**: Support 2-4 Machine Players in the same room
8. **Profiling Agent Framework**: Observer interface + basic statistical profiler
9. **History API + Replay Viewer**: Reconstruct games from ledger data

### Phase 3: Intelligence

10. **ML Player Models**: Trainable players (heuristic, MCTS, neural network)
11. **Advanced Profiling**: Behavioral pattern detection, play-style classification
12. **Unified Model Support**: Single model acting as both player and profiler
13. **External Model API**: Full REST interface for third-party model integration

---

## 11. Key Technical Decisions

| Decision | Rationale |
|---|---|
| **Intercept Socket.IO over DOM scraping** | The platform sends full game state via `takeTurnResponse`. Intercepting this is more reliable, faster, and less brittle than parsing CSS classes. DOM scraping serves as fallback. |
| **SQLite over PostgreSQL** | Single-server deployment, no concurrent write pressure. SQLite is zero-config and portable. Can migrate to PostgreSQL later if needed. |
| **Playwright over Selenium** | Better async support, built-in network interception, faster execution, native Python async API. |
| **FastAPI over Flask/Django** | Native async, auto-generated OpenAPI docs, Pydantic validation, WebSocket support built-in. |
| **Zustand over Redux** | Minimal boilerplate for a focused application. Easy to add WebSocket state sync. |
