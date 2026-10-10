"""Post-hoc profile analysis of a recorded session.

The ledger stores every move with its pre-move board snapshot, so any
registered Profiler can be replayed over a finished (or in-progress)
game after the fact — this powers the Profile Analyzer screen and lets
the team compare profiler implementations on identical data. Besides
the final profile, the analysis returns descriptive statistics per
player and the move-by-move evolution of the archetype classification
(the cold-start → confident transition the report describes).
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from tiles.agents.base import Profiler
from tiles.core import COLOR_NAMES, Action, GameState, apply_action, legal_actions


def _player_stats(records: List[dict], player_index: int) -> dict:
    mine = [r for r in records if r.get("player_index") == player_index]
    n = len(mine)
    if n == 0:
        return {
            "moves": 0,
            "final_score": 0,
            "color_distribution": {},
            "source_split": {},
            "destination_split": {},
            "row_preferences": {},
            "floor_rate": 0.0,
            "completion_rate": 0.0,
            "avg_decision_ms": 0.0,
            "avg_legal_actions": 0.0,
            "score_trajectory": [],
            "concepts": {},
        }

    colors = Counter(r["action"]["color"] for r in mine)
    sources = Counter(r["action"]["source_type"] for r in mine)
    dests = Counter(r["action"]["destination"] for r in mine)
    rows = Counter(
        str(r["action"]["destination_row"])
        for r in mine
        if r["action"]["destination"] == "pattern_line"
    )
    concepts: Counter = Counter()
    floor_moves = 0
    completions = 0
    decide_ms: List[float] = []
    legal_counts: List[int] = []
    trajectory: List[int] = []
    for r in mine:
        explanation = r.get("explanation") or {}
        concepts.update(explanation.get("concepts") or [])
        state_before = r.get("state_before")
        state_after = r.get("state_after")
        action = r["action"]
        if action["destination"] == "floor":
            floor_moves += 1
        elif state_before is not None:
            # Overflow or completion are visible by comparing pattern lines.
            try:
                before = state_before["players"][player_index]["pattern_lines"]
                after = (state_after or state_before)["players"][player_index][
                    "pattern_lines"
                ]
                row = action["destination_row"]
                taken = (
                    sum(1 for t in state_before["factories"][action["source_index"]]
                        if t == action["color"])
                    if action["source_type"] == "factory"
                    else sum(1 for t in state_before["center_pool"] if t == action["color"])
                )
                space = row + 1 - len(before[row])
                if taken > space:
                    floor_moves += 1
                if len(after[row]) == row + 1:
                    completions += 1
            except (KeyError, IndexError, TypeError):
                pass
        timing = r.get("timing") or {}
        if timing.get("decide_ms") is not None:
            decide_ms.append(float(timing["decide_ms"]))
        if state_before is not None:
            try:
                legal_counts.append(
                    len(legal_actions(GameState.from_dict(state_before)))
                )
            except Exception:  # noqa: BLE001 — malformed snapshot
                pass
        snapshot = state_after or state_before
        if snapshot is not None:
            try:
                trajectory.append(int(snapshot["players"][player_index]["score"]))
            except (KeyError, IndexError, TypeError):
                pass

    def share(counter: Counter) -> Dict[str, float]:
        return {k: round(v / n, 3) for k, v in sorted(counter.items())}

    return {
        "moves": n,
        "final_score": trajectory[-1] if trajectory else 0,
        "color_distribution": {
            c: round(colors.get(c, 0) / n, 3) for c in COLOR_NAMES
        },
        "source_split": share(sources),
        "destination_split": share(dests),
        "row_preferences": share(rows),
        "floor_rate": round(floor_moves / n, 3),
        "completion_rate": round(completions / n, 3),
        "avg_decision_ms": round(sum(decide_ms) / len(decide_ms), 2)
        if decide_ms
        else 0.0,
        "avg_legal_actions": round(sum(legal_counts) / len(legal_counts), 1)
        if legal_counts
        else 0.0,
        "score_trajectory": trajectory,
        "concepts": dict(concepts.most_common()),
    }


def analyze_session(
    records: List[dict],
    profiler: Profiler,
    player_names: Optional[Dict[int, str]] = None,
    tacticians: Optional[Dict[int, str]] = None,
) -> dict:
    """Replay ``records`` (TurnRecords, any order) through ``profiler``.

    Returns the ``POST /api/profiles/{id}/analyze`` payload minus the
    ``session_id``/``profiler`` envelope fields.
    """
    ordered = sorted(records, key=lambda r: r.get("step", 0))
    timelines: Dict[int, List[dict]] = {}
    seen_players: Dict[int, str] = dict(player_names or {})
    skipped = 0

    for record in ordered:
        state_before_dict = record.get("state_before")
        if not state_before_dict:
            skipped += 1
            continue
        try:
            state_before = GameState.from_dict(state_before_dict)
            action = Action.from_dict(record["action"])
            player = int(record.get("player_index", state_before.current_player))
            state_before.current_player = player
            move = apply_action(state_before.clone(), action)
        except (ValueError, KeyError, TypeError, IndexError):
            skipped += 1
            continue
        seen_players.setdefault(player, state_before.players[player].name)
        timing = record.get("timing") or {}
        profiler.observe(
            state_before, action, move, decision_ms=timing.get("decide_ms")
        )
        profile = profiler.profile(player)
        timelines.setdefault(player, []).append(
            {
                "step": record.get("step"),
                "archetype": profile.archetype,
                "confidence": round(profile.confidence, 3),
                "traits": {
                    k: round(v, 3) for k, v in profile.traits.items()
                },
            }
        )

    players = []
    for player in sorted(seen_players):
        profile = profiler.profile(player)
        players.append(
            {
                "player_index": player,
                "player_name": seen_players[player],
                "tactician": (tacticians or {}).get(player),
                "profile": profile.to_dict(),
                "stats": _player_stats(ordered, player),
                "timeline": timelines.get(player, []),
            }
        )
    return {
        "moves_analyzed": len(ordered) - skipped,
        "moves_skipped": skipped,
        "players": players,
    }
