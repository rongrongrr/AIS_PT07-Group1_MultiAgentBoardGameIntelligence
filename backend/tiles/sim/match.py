"""Local match runner: full offline games through the Decision Stack."""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from tiles.agents.base import Explainer, Profiler, Tactician
from tiles.agents.tacticians import make_tactician
from tiles.agents.validator import Validator
from tiles.core import GameState, deal_round, new_game
from tiles.ledger import Ledger
from tiles.orchestration import TurnPipeline, round_result_to_dict


def _make_profiler(name: Optional[str]) -> Optional[Profiler]:
    if not name:
        return None
    try:
        from tiles.agents.profiler import make_profiler
    except ImportError:
        return None
    return make_profiler(name)


def _make_explainer(name: Optional[str]) -> Optional[Explainer]:
    if not name:
        return None
    from tiles.agents.explainer import make_explainer

    return make_explainer(name)


@dataclass
class MatchConfig:
    """Configuration for one local game."""

    players: List[dict]  # [{"name": str, "tactician": str, "config": dict}]
    profiler: Optional[str] = "basic"
    explainer: Optional[str] = "template"
    seed: Optional[int] = None
    move_delay_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "mode": "local",
            "players": self.players,
            "profiler": self.profiler,
            "explainer": self.explainer,
            "seed": self.seed,
            "move_delay_ms": self.move_delay_ms,
        }


@dataclass
class MatchResult:
    session_id: str
    scores: List[int]
    winner: int
    winner_name: str
    steps: int
    rounds: int
    duration_s: float
    records: List[dict] = field(default_factory=list)
    profiles: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "scores": self.scores,
            "winner": self.winner,
            "winner_name": self.winner_name,
            "steps": self.steps,
            "rounds": self.rounds,
            "duration_s": round(self.duration_s, 3),
        }


class MatchRunner:
    """Runs one complete local game through the TurnPipeline.

    ``on_event`` receives WS-shaped events (docs/API.md): status, state,
    move, round, game_over. ``profiler``/``explainer`` instances may be
    injected directly, overriding the names in the config.
    """

    def __init__(
        self,
        config: MatchConfig,
        ledger: Optional[Ledger] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        keep_records: bool = False,
        session_id: Optional[str] = None,
        profiler: Optional[Profiler] = None,
        explainer: Optional[Explainer] = None,
        stop_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        if not 2 <= len(config.players) <= 4:
            raise ValueError("Azul needs 2-4 players")
        self.config = config
        self.ledger = ledger
        self.on_event = on_event or (lambda event: None)
        self.keep_records = keep_records
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        self.stop_check = stop_check or (lambda: False)

        self.tacticians: dict[int, Tactician] = {
            i: make_tactician(p["tactician"], **(p.get("config") or {}))
            for i, p in enumerate(config.players)
        }
        self.profiler = profiler if profiler is not None else _make_profiler(
            config.profiler
        )
        self.explainer = (
            explainer if explainer is not None else _make_explainer(config.explainer)
        )
        self.pipeline = TurnPipeline(
            validator=Validator(),
            tacticians=self.tacticians,
            profiler=self.profiler,
            explainer=self.explainer,
        )

    # -- driver ---------------------------------------------------------------

    def run(self) -> MatchResult:
        start = time.perf_counter()
        rng = random.Random(self.config.seed)
        state: GameState = new_game(
            len(self.config.players),
            seed=self.config.seed,
            player_names=[p["name"] for p in self.config.players],
        )

        if self.profiler is not None:
            self.profiler.register_players([p.name for p in state.players])
        if self.ledger is not None:
            self.ledger.create_session(
                self.session_id,
                mode="local",
                config=self.config.to_dict(),
                status="running",
            )
        self.on_event({"type": "status", "status": "running"})
        self.on_event({"type": "state", "step": 0, "state": state.to_dict()})

        records: List[dict] = []
        step_index = 0
        aborted = False
        final_bonuses = None
        while not state.is_game_over:
            if self.stop_check():
                aborted = True
                break
            step_index += 1
            record, _move, round_result = self.pipeline.run_turn(
                state, step_index
            )
            if self.ledger is not None:
                self.ledger.record_move(self.session_id, record)
            if self.keep_records:
                records.append(record)
            self.on_event({"type": "move", "step": step_index, "record": record})
            self.on_event(
                {"type": "state", "step": step_index, "state": state.to_dict()}
            )
            if round_result is not None:
                round_dict = round_result_to_dict(round_result)
                if self.ledger is not None:
                    self.ledger.record_round(
                        self.session_id, round_result.round_number, round_dict
                    )
                self.on_event(
                    {
                        "type": "round",
                        "round": round_result.round_number,
                        "result": round_dict,
                    }
                )
                if round_result.game_over:
                    final_bonuses = round_result.bonuses
                else:
                    deal_round(state, rng)
            if self.config.move_delay_ms > 0:
                time.sleep(self.config.move_delay_ms / 1000)

        profiles: List[dict] = []
        if self.profiler is not None:
            profiles = [
                self.profiler.profile(i).to_dict()
                for i in range(state.num_players)
            ]
            if self.ledger is not None:
                self.ledger.save_profiles(self.session_id, profiles)

        winner = state.winner() if state.is_game_over else 0
        result = MatchResult(
            session_id=self.session_id,
            scores=state.scores(),
            winner=winner if winner is not None else 0,
            winner_name=state.players[winner].name
            if winner is not None
            else "",
            steps=step_index,
            rounds=state.round_number,
            duration_s=time.perf_counter() - start,
            records=records,
            profiles=profiles,
        )

        if aborted:
            if self.ledger is not None:
                self.ledger.set_status(self.session_id, "aborted")
            self.on_event({"type": "status", "status": "aborted"})
        else:
            if self.ledger is not None:
                self.ledger.finish_session(self.session_id, result.to_dict())
            self.on_event(
                {
                    "type": "game_over",
                    "winner": result.winner,
                    "scores": result.scores,
                    "bonuses": final_bonuses,
                }
            )
        return result
