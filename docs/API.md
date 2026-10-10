# TILES Backend API Contract

Base URL: `http://localhost:8000`. All routes prefixed `/api`.
This contract is the interface between the FastAPI server and the React
frontend; both sides code against this document.

## Sessions

### `POST /api/sessions`
Create a session (not started yet).
```json
{
  "mode": "local",                  // "local" (simulated) | "live" (buddyboardgames.com)
  "players": [
    {"name": "Athena", "tactician": "mcts_profiled", "config": {"simulations": 400}},
    {"name": "Bob",    "tactician": "greedy",        "config": {}}
  ],
  "profiler": "basic",              // profiler name or null
  "explainer": "template",          // "template" | "llm" | null
  "seed": 42,                       // optional, local mode only
  "move_delay_ms": 0,               // pace for watchability
  "live": {                         // live mode only
    "room_name": "tiles-demo-1",
    "platform_url": "https://buddyboardgames.com/azul",
    "headless": true
  }
}
```
→ `201 {"id": "sess_...", "status": "created", ...config echo}`
Player slots may also be `{"name": "Alice", "tactician": "human"}` in live
mode (a human joins via the room link).

### `GET /api/sessions` → list of session summaries (id, status, mode, players, created_at, scores)
### `GET /api/sessions/{id}` → full session detail incl. latest state snapshot
### `POST /api/sessions/{id}/start` → `{"status": "running"}` (game loop runs in background)
### `POST /api/sessions/{id}/stop` → `{"status": "aborted"}`
### `GET /api/tacticians` → `[{"name": "greedy", "uses_opponent_model": false, "description": ...}, ...]`

## Live updates

### `WS /api/sessions/{id}/ws`
Server pushes JSON events:
```json
{"type": "status", "status": "running"}
{"type": "state",  "step": 12, "state": { GameState.to_dict() }}
{"type": "move",   "step": 12, "record": { TurnRecord, see below }}
{"type": "round",  "round": 2, "result": { RoundResult summary }}
{"type": "game_over", "winner": 0, "scores": [61, 48], "bonuses": [...]}
{"type": "log",    "level": "info", "message": "..."}
```

### TurnRecord (also returned by history endpoints)
```json
{
  "step": 12,
  "round": 2,
  "player_index": 0,
  "player_name": "Athena",
  "tactician": "mcts_profiled",
  "action": {"source_type": "factory", "source_index": 2, "color": "red",
             "destination": "pattern_line", "destination_row": 3},
  "state_before": { GameState.to_dict() },
  "state_after":  { GameState.to_dict() },
  "explanation": {"text": "...", "concepts": ["BLOCKING"], "evidence": {...}},
  "report": { SearchReport.to_dict() — candidates, visits, q-values, PV },
  "profiles": {"1": { PlayerProfile.to_dict() }},
  "validation": {"ok": true, "violation": null, "attempts": 1},
  "timing": {"decide_ms": 231.5, "validate_ms": 0.1, "explain_ms": 3.2, "total_ms": 240.0}
}
```

## History & replay

### `GET /api/history/{session_id}` → `{"session": {...}, "moves": [TurnRecord, ...]}`
### `GET /api/history/{session_id}/export` → full JSON export (download)
### `GET /api/profiles/{session_id}` → `{"profiles": [PlayerProfile.to_dict(), ...]}`

## Health

### `GET /api/health` → `{"status": "ok", "version": "0.2.0"}`
