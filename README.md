# OppoProfile

AI-driven platform that plays the board game **Azul** on [buddyboardgames.com](https://buddyboardgames.com/azul) using automated Machine Players, while recording every move for replay and analysis.

## Quick Start

### Prerequisites

- **Python 3.9+**
- **Node.js 18+**
- **Chromium** (installed automatically by Playwright)

### 1. Backend Setup

```bash
cd backend

# Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API is now running at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

The UI is now running at `http://localhost:5173`.

### 3. Play a Game

1. Open `http://localhost:5173` in your browser
2. Enter a **Room Name** (or click Random)
3. Choose **Browser Mode**:
   - **Headed** — opens visible browser windows so you can watch the game live
   - **Headless** — no browser UI, faster
4. Configure **Player Slots** (2-4 players):
   - **GreedyPlayer** — heuristic ML player that maximizes wall scoring
   - **RandomPlayer** — picks random valid moves
   - **Human** — a real person joins via the room link
5. Click **Create Session**, then **Start**

Each bot launches its own Chromium browser, joins the room on buddyboardgames.com, and plays autonomously.

## Features

### Machine Players

| Player | Strategy |
|---|---|
| **GreedyPlayer** | Scores each legal action based on wall placement value, pattern line completion, end-game bonuses, and floor penalties. Picks the highest-scoring move. |
| **RandomPlayer** | Picks a uniformly random legal action. Useful as a baseline. |

### Game Monitor

- **Live board state** — factories, center pool, player boards updated in real time
- **Move Log** grouped by round — expandable moves showing full board visualization
- **Round scores** — points gained per round with accumulated totals
- **System Log** — detailed timing for each phase (ML decide, execute, confirm)
- **Export JSON** — download complete game data for analysis

### Human Players

When you add a Human slot, the session page shows a **join link** (buddyboardgames.com URL). Share it with the human player. Bots wait in the lobby until all humans join, then the host bot starts the game.

### Game Export

Completed games can be exported as JSON containing every move with full board snapshots. See [EXPORT_FORMAT.md](backend/EXPORT_FORMAT.md) for the schema.

- **UI**: Click "Export JSON" on a completed game in the Monitor
- **API**: `GET /api/history/{session_id}/export`

## Project Structure

```
oppo-profile/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── azul/
│   │   │   ├── rules.py         # Azul game rules + legal move generation
│   │   │   └── scoring.py       # Scoring utilities
│   │   ├── engine/
│   │   │   ├── play_engine.py   # Playwright browser orchestration
│   │   │   ├── action_executor.py  # Socket.IO move execution
│   │   │   └── state_parser.py  # Game state parsing (WS + DOM)
│   │   ├── ml/
│   │   │   ├── base.py          # MachinePlayer / ProfilerAgent ABCs
│   │   │   ├── greedy_player.py # Heuristic scoring player
│   │   │   ├── random_player.py # Random baseline player
│   │   │   └── registry.py      # Model registration
│   │   ├── models/
│   │   │   ├── db.py            # SQLAlchemy models + SQLite
│   │   │   └── schemas.py       # Pydantic schemas
│   │   └── routers/
│   │       ├── sessions.py      # Session CRUD + game orchestration
│   │       ├── players.py       # ML model listing
│   │       └── history.py       # Move history + export
│   ├── tests/                   # pytest test suite
│   ├── EXPORT_FORMAT.md         # Export JSON documentation
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── SessionConfig.tsx  # Session setup page
│   │   │   ├── GameMonitor.tsx    # Live monitor + replay viewer
│   │   │   └── PlayerBoard.tsx    # Board visualization
│   │   ├── stores/gameStore.ts    # Zustand state
│   │   └── api/client.ts          # API + WebSocket client
│   └── package.json
├── db/                            # SQLite database (auto-created)
└── PRD.md                         # Product requirements
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/sessions` | Create a new game session |
| `GET` | `/api/sessions` | List all sessions |
| `GET` | `/api/sessions/{id}` | Get session details |
| `POST` | `/api/sessions/{id}/start` | Start the game (launches browsers) |
| `POST` | `/api/sessions/{id}/stop` | Stop/abort a session |
| `WS` | `/api/sessions/{id}/ws` | WebSocket for live updates |
| `GET` | `/api/players` | List registered ML players |
| `GET` | `/api/history/{id}` | Move history with board snapshots |
| `GET` | `/api/history/{id}/export` | Export full game as JSON |

## Running Tests

```bash
cd backend
source venv/bin/activate
python -m pytest tests/ -v
```

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand |
| Backend | Python, FastAPI, SQLAlchemy, SQLite |
| Automation | Playwright (Chromium), Socket.IO protocol |
| ML | Python ABC interface, heuristic scoring |
