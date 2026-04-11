# TILES Game Export Format (v1.0)

## Overview

The export JSON file contains a complete record of an Azul game session played through TILES. It can be used for game replay, ML training data, player profiling analysis, or archival.

## How to Export

- **UI**: Open a completed game in the Game Monitor, click **"Export JSON"** button
- **API**: `GET /api/history/{session_id}/export`

## Structure

```
{
  "export_version": "1.0",
  "session": { ... },     // Session metadata
  "summary": { ... },     // Game summary with round scores
  "moves": [ ... ]        // Every move with full board state
}
```

### `session` — Session Metadata

| Field | Type | Description |
|---|---|---|
| `id` | string | Session ID (e.g. `sess_abc123`) |
| `room_name` | string | Room name on buddyboardgames.com |
| `platform_url` | string | Game platform URL |
| `browser_mode` | string | `headless` or `headed` |
| `status` | string | `completed`, `aborted`, etc. |
| `player_config` | array | Player slot configurations |
| `move_timeout_sec` | int | Max seconds per move |
| `created_at` | string | ISO timestamp |
| `completed_at` | string | ISO timestamp |

### `summary` — Game Summary

| Field | Type | Description |
|---|---|---|
| `total_moves` | int | Total number of moves in the game |
| `total_rounds` | int | Number of rounds played |
| `rounds` | array | Per-round summary (see below) |
| `final_scores` | object | `{"Alice": 21, "Bob": 15}` |

Each `rounds[i]`:
```json
{
  "round": 1,
  "moves": 13,
  "end_scores": {"Alice": 5, "Bob": 3}
}
```

### `moves` — Move List

Each move represents one player action (pick tiles from source, place on destination).

| Field | Type | Description |
|---|---|---|
| `step_id` | int | Sequential move number (1-based) |
| `player_name` | string | Who made this move |
| `system_tag` | string | ML model name (e.g. `GreedyPlayer`) |
| `action.source_type` | string | `factory` or `center` |
| `action.source_index` | int/null | Factory index (0-based), null for center |
| `action.color` | string | Tile color: `blue`, `yellow`, `red`, `black`, `white` |
| `action.destination` | string | `pattern_line` or `floor` |
| `action.destination_row` | int/null | Pattern line row (0-4), null for floor |
| `decision_time_ms` | int | Time the ML model took to decide |
| `timestamp` | string | ISO timestamp of the move |
| `round` | int | Which round this move belongs to |
| `scores` | object | Scores after this move: `{"Alice": 5, "Bob": 3}` |
| `total_ms` | int | Total time for the move (decide + execute + confirm) |
| `click_ms` | int | Time to execute the move on the platform |
| `ws_wait_ms` | int | Time waiting for server confirmation |
| `legal_actions` | int | Number of legal actions available |
| `board` | object | Full board state snapshot (see below) |

### `board` — Board State Snapshot

Captured **before** each move. Shows the exact game state the ML model saw when making its decision.

```json
{
  "factories": [
    ["red", "blue", "yellow", "red"],
    ["black", "white", "blue", "yellow"],
    ...
  ],
  "center_pool": ["red", "firstPlayer"],
  "players": [
    {
      "name": "Alice",
      "score": 5,
      "pattern_lines": [
        ["red"],           // row 0: 1 slot, has red
        [],                // row 1: 2 slots, empty
        ["blue", "blue"],  // row 2: 3 slots, 2 filled
        [],                // row 3: empty
        []                 // row 4: empty
      ],
      "wall": [
        [true, false, false, false, false],  // row 0
        [false, false, false, false, false], // row 1
        ...
      ],
      "floor_line": ["yellow"]
    },
    ...
  ]
}
```

#### Wall Color Pattern

The standard Azul wall has a fixed color pattern. `wall[row][col] = true` means the tile is placed. The color at each position:

```
Row 0: blue,   yellow, red,    black,  white
Row 1: white,  blue,   yellow, red,    black
Row 2: black,  white,  blue,   yellow, red
Row 3: red,    black,  white,  blue,   yellow
Row 4: yellow, red,    black,  white,  blue
```

#### Tile Colors

| Color | Platform Display |
|---|---|
| `blue` | Sky blue tile |
| `yellow` | Bright yellow tile |
| `red` | Coral/pink tile |
| `black` | Light green tile (platform uses green for "black") |
| `white` | White/cream tile |
| `firstPlayer` | First player token (aquamarine) |

## Reading the Export

1. **Replay**: Iterate through `moves` array. Each move has a `board` snapshot showing the state BEFORE the move was made, and an `action` showing what was done.

2. **Round boundaries**: Use `summary.rounds` to see how many moves per round and scores at each round end.

3. **Scoring analysis**: The `scores` field on each move shows cumulative scores. Compare consecutive moves to see point changes.

4. **ML analysis**: `decision_time_ms` and `legal_actions` show how the ML model performed. The `board` snapshot is the exact input the model received.
