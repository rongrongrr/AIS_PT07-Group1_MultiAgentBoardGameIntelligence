"""Profile Analyzers — analyze player behavior from game move history.

Pluggable architecture: implement the ProfileAnalyzer ABC and register
via the analyzer_registry.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
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
    def analyze(self, player_name: str, moves: List[dict]) -> dict:
        """Analyze a player's moves and return a profile.

        Args:
            player_name: The player to analyze.
            moves: List of move dicts (from the history API) for the entire game.

        Returns:
            A dict with profile data. Must include a "summary" key with
            a human-readable description.
        """
        ...


class BasicProfileAnalyzer(ProfileAnalyzer):
    """Analyzes basic play patterns: color preferences, source preferences,
    floor usage, timing, and aggressiveness."""

    @property
    def name(self) -> str:
        return "BasicProfileAnalyzer"

    @property
    def description(self) -> str:
        return "Analyzes play patterns: color/source preferences, floor usage, timing, scoring efficiency."

    def analyze(self, player_name: str, moves: List[dict]) -> dict:
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
        final_score = scores_over_time[-1] if scores_over_time else 0

        # Build profile
        color_dist = {c: round(n / total * 100) for c, n in colors.most_common()}
        row_dist = {f"row_{r}": round(n / total * 100) for r, n in sorted(rows.items())}

        # Generate summary
        style_traits = []
        if floor_pct > 20:
            style_traits.append("aggressive (high floor usage)")
        elif floor_pct < 5:
            style_traits.append("conservative (avoids floor)")
        if center_pct > 40:
            style_traits.append("center-focused")
        if factory_pct > 70:
            style_traits.append("factory-focused")
        if fav_color[1] / total > 0.3:
            style_traits.append(f"{fav_color[0]}-biased")

        style = ", ".join(style_traits) if style_traits else "balanced"

        summary = (
            f"{player_name} played {total} moves across the game, scoring {final_score} points. "
            f"Play style: {style}. "
            f"Favorite color: {fav_color[0]} ({round(fav_color[1]/total*100)}% of picks). "
            f"Source split: {factory_pct}% factory / {center_pct}% center. "
            f"Floor usage: {floor_pct}% of placements. "
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
            "row_preferences": row_dist,
            "timing": {"avg_total_ms": avg_time, "avg_decide_ms": avg_decide},
            "score_trajectory": scores_over_time,
        }


class AnalyzerRegistry:
    """Registry for pluggable profile analyzers."""

    def __init__(self):
        self._analyzers: Dict[str, ProfileAnalyzer] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register(BasicProfileAnalyzer())

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
