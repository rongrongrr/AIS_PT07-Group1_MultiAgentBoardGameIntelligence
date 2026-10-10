"""Rule verification: the accuracy benchmark for rule extraction.

Third stage of the RAG-to-Logic pipeline. Every extracted RuleSpec is
checked against the deterministic rules engine as ground truth — either
by comparing extracted parameters with engine constants, or by
behavioral probes: constructing minimal game states in which the engine
must raise exactly the predicate the spec claims to describe.

Run standalone:  python -m tiles.rulebook.verify
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from tiles.core import (
    BLUE,
    CENTER,
    FIRST_PLAYER,
    FLOOR,
    FLOOR_PENALTIES,
    NUM_COLORS,
    PHASE_GAME_OVER,
    RED,
    Action,
    GameState,
    apply_action,
    check_action,
    end_game_bonuses,
    legal_actions,
    new_game,
    placement_score,
    resolve_round,
    wall_col_for,
)
from tiles.core.simulator import draw_tiles
from tiles.core.state import TILES_PER_COLOR, PlayerBoard, factories_for_players, wall_bit

from .extract import RuleSpec, extract_rules_deterministic
from .ingest import RulebookIndex


@dataclass
class CheckResult:
    rule_id: str
    ok: bool
    detail: str = ""


@dataclass
class VerificationReport:
    checks: List[CheckResult] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.checks) + len(self.skipped)

    @property
    def verified(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def mismatches(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.ok]

    @property
    def accuracy(self) -> float:
        return self.verified / len(self.checks) if self.checks else 0.0

    def summary_table(self) -> str:
        lines = [
            f"{'rule':<22} {'status':<10} detail",
            "-" * 70,
        ]
        for check in self.checks:
            status = "VERIFIED" if check.ok else "MISMATCH"
            lines.append(f"{check.rule_id:<22} {status:<10} {check.detail}")
        for rule_id in self.skipped:
            lines.append(f"{rule_id:<22} {'SKIPPED':<10} no checker registered")
        lines.append("-" * 70)
        lines.append(
            f"{self.verified}/{len(self.checks)} verified "
            f"({self.accuracy:.0%} accuracy), {len(self.skipped)} skipped"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------


def _expect_predicate(
    state: GameState, action: Action, expected: Optional[str]
) -> Optional[str]:
    violation = check_action(state, action)
    got = violation.predicate if violation else None
    if got != expected:
        return f"engine raised {got!r}, spec claims {expected!r}"
    return None


# ---------------------------------------------------------------------------
# Checkers (one per rule id) — return None if verified, else mismatch detail
# ---------------------------------------------------------------------------


def _check_floor_penalties(spec: RuleSpec) -> Optional[str]:
    extracted = list(spec.parameters.get("penalties", []))
    if extracted != list(FLOOR_PENALTIES):
        return f"extracted {extracted}, engine uses {list(FLOOR_PENALTIES)}"
    return None


def _check_endgame_bonuses(spec: RuleSpec) -> Optional[str]:
    # One complete horizontal row, nothing else complete.
    row_board = PlayerBoard()
    for c in range(5):
        row_board.wall |= wall_bit(0, c)
    # One complete vertical column.
    col_board = PlayerBoard()
    for r in range(5):
        col_board.wall |= wall_bit(r, 0)
    # All five tiles of one color.
    color_board = PlayerBoard()
    for r in range(5):
        color_board.wall |= wall_bit(r, wall_col_for(r, BLUE))
    engine = {
        "row": end_game_bonuses(row_board)["points"],
        "col": end_game_bonuses(col_board)["points"],
        "color": end_game_bonuses(color_board)["points"],
    }
    for key, engine_value in engine.items():
        if spec.parameters.get(key) != engine_value:
            return (
                f"{key} bonus: extracted {spec.parameters.get(key)}, "
                f"engine scores {engine_value}"
            )
    return None


def _check_placement_scoring(spec: RuleSpec) -> Optional[str]:
    isolated = placement_score(wall_bit(2, 2), 2, 2)
    if spec.parameters.get("isolated") != isolated:
        return f"isolated tile: extracted {spec.parameters.get('isolated')}, engine {isolated}"
    # Cross-check the chain rule: horizontal 3 + vertical 2.
    wall = wall_bit(2, 1) | wall_bit(2, 2) | wall_bit(2, 3) | wall_bit(1, 2)
    if placement_score(wall, 2, 2) != 5:
        return "engine adjacency scoring does not match chain rule"
    return None


def _check_min_score(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.players[0].floor = [RED] * 7
    resolve_round(state)
    floor = spec.parameters.get("min_score")
    if state.players[0].score != floor:
        return f"engine clamps at {state.players[0].score}, extracted floor {floor}"
    return None


def _check_factory_counts(spec: RuleSpec) -> Optional[str]:
    for players, factories in spec.parameters.get("factories_by_players", {}).items():
        engine_value = factories_for_players(int(players))
        if engine_value != factories:
            return (
                f"{players} players: extracted {factories}, engine {engine_value}"
            )
    return None


def _check_tile_supply(spec: RuleSpec) -> Optional[str]:
    p = spec.parameters
    if p.get("tiles_per_color") != TILES_PER_COLOR:
        return f"tiles per color: extracted {p.get('tiles_per_color')}, engine {TILES_PER_COLOR}"
    if p.get("colors") != NUM_COLORS:
        return f"colors: extracted {p.get('colors')}, engine {NUM_COLORS}"
    if p.get("total") != TILES_PER_COLOR * NUM_COLORS:
        return f"total: extracted {p.get('total')}, engine {TILES_PER_COLOR * NUM_COLORS}"
    return None


def _check_factory_fill(spec: RuleSpec) -> Optional[str]:
    state = new_game(2, seed=0)
    per_factory = spec.parameters.get("tiles_per_factory")
    if any(sum(f) != per_factory for f in state.factories):
        return f"engine deals {sum(state.factories[0])} per factory, extracted {per_factory}"
    return None


def _check_draft_take_all(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.factories[0][BLUE] = 2
    state.factories[0][RED] = 1
    # Negative probe: drafting an absent color must violate the predicate.
    mismatch = _expect_predicate(
        state, Action(0, 3, FLOOR), spec.predicate  # BLACK not present
    )
    if mismatch:
        return mismatch
    # Positive probe: drafting takes ALL tiles of the color.
    move = apply_action(state.clone(), Action(0, BLUE, FLOOR))
    if move.tiles_taken != 2:
        return f"engine took {move.tiles_taken} of 2 tiles"
    return None


def _check_wall_duplicate(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.factories[0][BLUE] = 1
    state.players[0].wall |= wall_bit(2, wall_col_for(2, BLUE))
    return _expect_predicate(state, Action(0, BLUE, 2), spec.predicate)


def _check_line_single_color(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.factories[0][RED] = 1
    state.players[0].pattern_colors[3] = BLUE
    state.players[0].pattern_counts[3] = 1
    return _expect_predicate(state, Action(0, RED, 3), spec.predicate)


def _check_line_capacity(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.factories[0][BLUE] = 1
    state.players[0].pattern_colors[0] = BLUE
    state.players[0].pattern_counts[0] = 1  # row 0 full
    return _expect_predicate(state, Action(0, BLUE, 0), spec.predicate)


def _check_game_over_no_moves(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.factories[0][BLUE] = 1
    state.phase = PHASE_GAME_OVER
    mismatch = _expect_predicate(state, Action(0, BLUE, FLOOR), spec.predicate)
    if mismatch:
        return mismatch
    if legal_actions(state):
        return "engine still offers legal actions after game over"
    return None


def _check_valid_color(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.factories[0][BLUE] = 1
    return _expect_predicate(state, Action(0, 9, FLOOR), spec.predicate)


def _check_valid_source(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)  # factories 0..4 only
    return _expect_predicate(state, Action(7, BLUE, FLOOR), spec.predicate)


def _check_valid_destination(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.factories[0][BLUE] = 1
    return _expect_predicate(state, Action(0, BLUE, 9), spec.predicate)


def _check_first_player_token(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.center[BLUE] = 2
    apply_action(state, Action(CENTER, BLUE, FLOOR))
    if FIRST_PLAYER not in state.players[0].floor:
        return "engine did not move the token to the floor line"
    if state.next_first_player != 0:
        return "engine did not grant the next first turn"
    return None


def _check_game_end_trigger(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    board = state.players[0]
    for c in range(4):
        board.wall |= wall_bit(0, c)
    missing_color = (4 - 0) % 5  # color of row 0, col 4
    board.pattern_colors[0] = missing_color
    board.pattern_counts[0] = 1
    result = resolve_round(state)
    if not result.game_over or not state.is_game_over:
        return "engine did not end the game on a completed row"
    return None


def _check_bag_refill(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.bag = [0] * NUM_COLORS
    state.lid = [1, 0, 0, 0, 0]
    drawn = draw_tiles(state, 1, random.Random(0))
    if drawn != [BLUE]:
        return "engine did not refill the bag from the lid"
    return None


def _check_tie_break(spec: RuleSpec) -> Optional[str]:
    state = GameState(num_players=2)
    state.phase = PHASE_GAME_OVER
    for player in state.players:
        player.score = 10
    for c in range(5):
        state.players[1].wall |= wall_bit(0, c)
    if state.winner() != 1:
        return "engine tie-break does not prefer completed rows"
    return None


_CHECKERS: Dict[str, Callable[[RuleSpec], Optional[str]]] = {
    "floor_penalties": _check_floor_penalties,
    "endgame_bonuses": _check_endgame_bonuses,
    "placement_scoring": _check_placement_scoring,
    "score_floor_zero": _check_min_score,
    "factory_counts": _check_factory_counts,
    "tile_supply": _check_tile_supply,
    "factory_fill": _check_factory_fill,
    "draft_take_all": _check_draft_take_all,
    "wall_duplicate": _check_wall_duplicate,
    "line_single_color": _check_line_single_color,
    "line_capacity": _check_line_capacity,
    "game_over_no_moves": _check_game_over_no_moves,
    "valid_color": _check_valid_color,
    "valid_source": _check_valid_source,
    "valid_destination": _check_valid_destination,
    "first_player_token": _check_first_player_token,
    "game_end_trigger": _check_game_end_trigger,
    "bag_refill": _check_bag_refill,
    "tie_break": _check_tie_break,
}


def verify_rules(specs: List[RuleSpec]) -> VerificationReport:
    """Check every extracted rule against the engine as ground truth."""
    report = VerificationReport()
    for spec in specs:
        checker = _CHECKERS.get(spec.id)
        if checker is None:
            report.skipped.append(spec.id)
            continue
        try:
            detail = checker(spec)
        except Exception as exc:  # a broken probe is a mismatch, not a crash
            detail = f"probe raised {type(exc).__name__}: {exc}"
        report.checks.append(
            CheckResult(rule_id=spec.id, ok=detail is None, detail=detail or "")
        )
    return report


def main() -> None:
    index = RulebookIndex.build()
    specs = extract_rules_deterministic(index)
    print(f"Extracted {len(specs)} rules from rulebook.md")
    report = verify_rules(specs)
    print(report.summary_table())


if __name__ == "__main__":
    main()
