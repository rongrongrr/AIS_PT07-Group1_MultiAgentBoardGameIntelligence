"""Rule parameters that can come from an ingested rulebook.

The defaults are the standard Azul values. ``app.rules_ingest`` extracts the same
parameters from rulebook text and builds a ``RulesConfig`` from them, which the scoring
functions and the game simulator accept, so the validator can be driven by ingested rules.

The wall layout is *not* configurable here: legality checks are written against the
standard layout, so ingestion verifies the extracted layout against it instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class RulesConfig:
    floor_penalties: Tuple[int, ...] = (-1, -1, -2, -2, -2, -3, -3)
    row_bonus: int = 2
    column_bonus: int = 7
    color_bonus: int = 10
    tiles_per_color: int = 20
    tiles_per_factory: int = 4
    factories_by_players: Dict[int, int] = field(default_factory=lambda: {2: 5, 3: 7, 4: 9})

    def factory_count(self, num_players: int) -> int:
        return self.factories_by_players[num_players]


DEFAULT_RULES = RulesConfig()
