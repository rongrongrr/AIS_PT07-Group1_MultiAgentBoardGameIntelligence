"""Profile Analyzers — analyze player behavior from game move history.

Pluggable architecture: implement the ProfileAnalyzer ABC and register
via the analyzer_registry.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import Counter
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ProfileAnalyzer(ABC):
    """Abstract base class for all profile analyzers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this analyzer does."""
        ...

    @abstractmethod
    def analyze(self, player_name: str, moves: List[dict], final_scores: Optional[dict] = None) -> dict:
        """Analyze a player's moves and return a profile.

        Args:
            player_name: The player to analyze.
            moves: List of move dicts (from the history API) for the entire game.
            final_scores: The session's recorded final scores, when the game is complete. Board
                snapshots are taken *before* each move, so without this the last round's scoring
                and the end-of-game bonuses are missing from the score.

        Returns:
            A dict with profile data. Must include a "summary" key with
            a human-readable description.
        """
        ...


def _tiles_to_floor(move: dict, player_name: str) -> Optional[tuple]:
    """(tiles taken, tiles that end up on the floor) for one move, or None without a board snapshot.

    Taking tiles straight to the floor sends them all there; placing on a pattern line sends the
    overflow beyond the line's free space. The first-player token is not counted as a tile.
    """
    board = move.get("board")
    action = move.get("action") or {}
    if not board:
        return None
    color = action.get("color")
    try:
        if action.get("source_type") == "factory":
            picked = sum(1 for t in board["factories"][action["source_index"]] if t == color)
        else:
            picked = sum(1 for t in board["center_pool"] if t == color)
        if action.get("destination") == "floor":
            return picked, picked
        me = next(p for p in board["players"] if p["name"] == player_name)
        row = action["destination_row"]
        space = (row + 1) - len(me["pattern_lines"][row])
        return picked, max(0, picked - space)
    except (KeyError, IndexError, TypeError, StopIteration):
        return None


class BasicProfileAnalyzer(ProfileAnalyzer):
    """Analyzes basic play patterns: color preferences, source preferences,
    floor usage, timing, and aggressiveness."""

    @property
    def name(self) -> str:
        return "BasicProfileAnalyzer"

    @property
    def description(self) -> str:
        return "Analyzes play patterns: color/source preferences, floor usage, timing, scoring efficiency."

    def analyze(self, player_name: str, moves: List[dict], final_scores: Optional[dict] = None) -> dict:
        player_moves = [m for m in moves if m.get("player_name") == player_name]
        if not player_moves:
            return {"summary": f"No moves found for {player_name}."}

        total = len(player_moves)

        # Color preferences
        colors = Counter(m["action"]["color"] for m in player_moves)
        fav_color = colors.most_common(1)[0] if colors else ("unknown", 0)

        # Source preferences
        sources = Counter(m["action"]["source_type"] for m in player_moves)
        factory_pct = round(sources.get("factory", 0) / total * 100)
        center_pct = round(sources.get("center", 0) / total * 100)

        # Destination preferences
        dests = Counter(m["action"]["destination"] for m in player_moves)
        floor_pct = round(dests.get("floor", 0) / total * 100)
        pattern_pct = round(dests.get("pattern_line", 0) / total * 100)

        # Row preferences
        rows = Counter(
            m["action"]["destination_row"]
            for m in player_moves
            if m["action"]["destination"] == "pattern_line" and m["action"]["destination_row"] is not None
        )

        # Timing
        times = [m.get("total_ms", 0) for m in player_moves if m.get("total_ms")]
        avg_time = round(sum(times) / len(times)) if times else 0
        decide_times = [m.get("decision_time_ms", 0) for m in player_moves if m.get("decision_time_ms") is not None]
        avg_decide = round(sum(decide_times) / len(decide_times)) if decide_times else 0

        # Scoring trajectory
        scores_over_time = []
        for m in player_moves:
            s = m.get("scores", {})
            if player_name in s:
                scores_over_time.append(s[player_name])
        # Score: the session's recorded final score if the game is complete; otherwise the most recent
        # score anyone's snapshot shows for this player (later moves by other players are newer than
        # this player's own last move).
        latest = next((m["scores"][player_name] for m in reversed(moves)
                       if player_name in (m.get("scores") or {})), None)
        final = (final_scores or {}).get(player_name)
        final_score = final if final is not None else (latest if latest is not None else 0)
        score_is_final = final is not None
        if scores_over_time and score_is_final and scores_over_time[-1] != final_score:
            scores_over_time.append(final_score)

        # Floor: moves sent straight to the floor, and tiles that end up there (including overflow)
        counted = [t for t in (_tiles_to_floor(m, player_name) for m in player_moves) if t is not None]
        taken = sum(t[0] for t in counted)
        on_floor = sum(t[1] for t in counted)
        floor_tiles = ({"taken": taken, "on_floor": on_floor, "pct": round(on_floor / taken * 100)}
                       if taken else None)

        # Build profile
        color_dist = {c: round(n / total * 100) for c, n in colors.most_common()}
        row_dist = {f"row_{r}": round(n / total * 100) for r, n in sorted(rows.items())}

        # Generate summary
        style_traits = []
        floor_basis = floor_tiles["pct"] if floor_tiles else floor_pct      # tiles are the real cost when known
        if floor_basis > 20:
            style_traits.append("aggressive (high floor usage)")
        elif floor_basis < 5:
            style_traits.append("conservative (avoids floor)")
        if center_pct > 40:
            style_traits.append("center-focused")
        if factory_pct > 70:
            style_traits.append("factory-focused")
        if fav_color[1] / total > 0.3:
            style_traits.append(f"{fav_color[0]}-biased")

        style = ", ".join(style_traits) if style_traits else "balanced"

        floor_text = (
            f"Floor: {floor_pct}% of moves went straight to the floor; {floor_tiles['pct']}% of the tiles taken "
            f"({floor_tiles['on_floor']} of {floor_tiles['taken']}) ended on the floor, counting overflow. "
            if floor_tiles else f"Floor usage: {floor_pct}% of moves went straight to the floor. "
        )
        score_text = (f"finished with {final_score} points" if score_is_final
                      else f"had {final_score} points at the latest recorded position")
        summary = (
            f"{player_name} played {total} moves across the game and {score_text}. "
            f"Play style: {style}. "
            f"Favorite color: {fav_color[0]} ({round(fav_color[1]/total*100)}% of picks). "
            f"Source split: {factory_pct}% factory / {center_pct}% center. "
            f"{floor_text}"
            f"Average decision time: {avg_decide}ms."
        )

        return {
            "summary": summary,
            "player_name": player_name,
            "total_moves": total,
            "final_score": final_score,
            "style": style,
            "color_preferences": color_dist,
            "source_split": {"factory": factory_pct, "center": center_pct},
            "destination_split": {"pattern_line": pattern_pct, "floor": floor_pct},
            "floor_tiles": floor_tiles,
            "score_is_final": score_is_final,
            "row_preferences": row_dist,
            "timing": {"avg_total_ms": avg_time, "avg_decide_ms": avg_decide},
            "score_trajectory": scores_over_time,
        }


class ArchetypeProfileAnalyzer(ProfileAnalyzer):
    """BasicProfileAnalyzer statistics plus an archetype label from a trained classifier.

    The classifier is trained on simulated self-play between style-weighted bots
    (scripts/train_archetypes.py) and applied here to ledger games. Treat the
    label as a hypothesis: it is per-game, trained on bot styles, and held-out
    accuracy is stored in models/archetype_classifier.json (meta).
    """

    def __init__(self, model):
        self._basic = BasicProfileAnalyzer()
        self._model = model

    @property
    def name(self) -> str:
        return "ArchetypeProfileAnalyzer"

    @property
    def description(self) -> str:
        return "Basic statistics plus a learned play-style archetype with feature-level reasons."

    def analyze(self, player_name: str, moves: List[dict], final_scores: Optional[dict] = None) -> dict:
        from tiles.ml.archetypes import extract_features

        profile = self._basic.analyze(player_name, moves, final_scores)
        if "total_moves" not in profile:
            return profile
        feats = extract_features(moves, player_name)
        if feats is None:
            profile["archetype"] = None
            profile["summary"] += " Archetype: not enough moves with board snapshots to classify."
            return profile
        pred = self._model.predict(feats)
        profile.update({
            "archetype": pred.archetype,
            "archetype_confidence": pred.confidence,
            "archetype_scores": pred.scores,
            "archetype_reasons": pred.standout_features,
        })
        reasons = "; ".join(r["meaning"] for r in pred.standout_features) or "no single dominant trait"
        profile["summary"] += (
            f" Archetype: {pred.archetype} ({pred.confidence:.0%} confidence) because {reasons}."
        )
        return profile


class SequenceProfileAnalyzer(ProfileAnalyzer):
    """BasicProfileAnalyzer statistics plus an archetype from the sequence model (Transformer/GRU
    over the player's move sequence), with saliency-based reasons."""

    def __init__(self, model):
        self._basic = BasicProfileAnalyzer()
        self._model = model

    @property
    def name(self) -> str:
        return "SequenceProfileAnalyzer"

    @property
    def description(self) -> str:
        return f"Basic statistics plus a {self._model.kind} sequence model over the move sequence."

    def analyze(self, player_name: str, moves: List[dict], final_scores: Optional[dict] = None) -> dict:
        profile = self._basic.analyze(player_name, moves, final_scores)
        if "total_moves" not in profile:
            return profile
        pred = self._model.predict(moves, player_name)
        if pred is None:
            profile["archetype"] = None
            profile["summary"] += " Archetype: no moves with board snapshots to classify."
            return profile
        profile.update({
            "archetype": pred.archetype,
            "archetype_confidence": pred.confidence,
            "archetype_scores": pred.scores,
            "archetype_reasons": [{"feature": r["feature"], "value": r["importance"], "z": 0,
                                   "meaning": r["meaning"]} for r in pred.standout_features],
            "model_kind": self._model.kind,
        })
        profile["summary"] += (f" Archetype ({self._model.kind}): {pred.archetype} "
                               f"({pred.confidence:.0%} confidence).")
        return profile


class AnalyzerRegistry:
    """Registry for pluggable profile analyzers."""

    def __init__(self):
        self._analyzers: Dict[str, ProfileAnalyzer] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register(BasicProfileAnalyzer())
        try:
            from tiles.ml.archetypes import DEFAULT_MODEL_PATH, ArchetypeClassifier

            if DEFAULT_MODEL_PATH.exists():
                self.register(ArchetypeProfileAnalyzer(ArchetypeClassifier.load(DEFAULT_MODEL_PATH)))
        except Exception:  # missing numpy/model or feature mismatch: keep the basic analyzer only
            logger.exception("Archetype analyzer unavailable")
        try:
            from tiles.ml.sequence_profiler import DEFAULT_SEQ_MODEL_PATH, SequenceProfiler

            if DEFAULT_SEQ_MODEL_PATH.exists():
                self.register(SequenceProfileAnalyzer(SequenceProfiler.load(DEFAULT_SEQ_MODEL_PATH)))
        except Exception:  # torch not installed or model mismatch
            logger.warning("Sequence profile analyzer unavailable", exc_info=True)

    def register(self, analyzer: ProfileAnalyzer):
        self._analyzers[analyzer.name] = analyzer

    def get(self, name: str) -> Optional[ProfileAnalyzer]:
        return self._analyzers.get(name)

    def list_all(self) -> List[dict]:
        return [
            {"name": a.name, "description": a.description}
            for a in self._analyzers.values()
        ]


analyzer_registry = AnalyzerRegistry()
