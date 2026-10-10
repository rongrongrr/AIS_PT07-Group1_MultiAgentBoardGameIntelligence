"""External (remote) Machine Players: any HTTP service can play as a bot.

Contract (the same one this platform serves at ``POST /api/player/action``)::

    request : {"state": <GameStateData JSON>, "player_index": 0, "legal_actions": [<GameAction JSON>, ...]}
    response: {"action": <GameAction JSON>}        (a bare GameAction object is also accepted)

The platform still validates every returned move against the rules engine before executing it, so a
faulty or hostile remote model cannot make an illegal move.
"""

from __future__ import annotations

from typing import Optional

import httpx

from app.azul.rules import get_legal_actions
from app.ml.base import MachinePlayer
from app.models.schemas import GameAction, GameStateData


class RemotePlayer(MachinePlayer):
    def __init__(self, name: str, url: str, timeout: float = 8.0, client: Optional[httpx.AsyncClient] = None):
        self._name = name
        self.url = url
        self.timeout = timeout
        self._client = client            # injected in tests; created per call otherwise
        self.last_explanation: dict = {"model": name, "method": f"remote model at {url}"}

    @property
    def name(self) -> str:
        return self._name

    def clone(self) -> "RemotePlayer":
        return RemotePlayer(self._name, self.url, self.timeout, self._client)

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        legal = get_legal_actions(game_state, player_index)
        if not legal:
            raise ValueError("No legal actions available")
        payload = {
            "state": game_state.model_dump(mode="json"),
            "player_index": player_index,
            "legal_actions": [a.model_dump(mode="json") for a in legal],
        }
        if self._client is not None:
            resp = await self._client.post(self.url, json=payload, timeout=self.timeout)
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        action = GameAction(**(data.get("action", data) if isinstance(data, dict) else data))
        if action not in legal:
            raise ValueError(f"remote model '{self._name}' returned an illegal action")
        return action
