"""PettingZoo AEC environment for Azul.

Azul is sequential and turn-based, so the Agent-Environment-Cycle API is
the natural wrapper (per the architecture report). Observations pair the
flat float encoding from ``tiles.core.encode`` with the 300-slot legal
action mask; rewards are per-round score deltas dispensed on the agent's
next actionable step, with final win/loss added at termination.

Requires the ``rl`` extra (pettingzoo, gymnasium, numpy).
"""

from __future__ import annotations

import random
from typing import Optional

try:
    import numpy as np
    from gymnasium import spaces
    from pettingzoo import AECEnv
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "the RL environment needs the 'rl' extra: pip install 'tiles[rl]'"
    ) from exc

from tiles.core import MAX_ACTIONS, Action, deal_round, legal_action_mask, new_game, step
from tiles.core.encode import OBS_SIZE, encode_state


class AzulAECEnv(AECEnv):
    metadata = {"name": "azul_v0", "is_parallelizable": False}

    def __init__(
        self, num_players: int = 2, seed: Optional[int] = None
    ) -> None:
        super().__init__()
        self.num_players_config = num_players
        self._seed = seed
        self.possible_agents = [f"player_{i}" for i in range(num_players)]
        self.observation_spaces = {
            a: spaces.Dict(
                {
                    "observation": spaces.Box(
                        low=-1.0, high=1.0, shape=(OBS_SIZE,), dtype=np.float32
                    ),
                    "action_mask": spaces.Box(
                        low=0, high=1, shape=(MAX_ACTIONS,), dtype=np.int8
                    ),
                }
            )
            for a in self.possible_agents
        }
        self.action_spaces = {
            a: spaces.Discrete(MAX_ACTIONS) for a in self.possible_agents
        }

    # -- pettingzoo API -------------------------------------------------------

    def observation_space(self, agent):
        return self.observation_spaces[agent]

    def action_space(self, agent):
        return self.action_spaces[agent]

    def observe(self, agent: str):
        index = self.possible_agents.index(agent)
        obs = np.asarray(
            encode_state(self.state_, index), dtype=np.float32
        )
        if agent == self.agent_selection and not self.terminations[agent]:
            mask = np.asarray(legal_action_mask(self.state_), dtype=np.int8)
        else:
            mask = np.zeros(MAX_ACTIONS, dtype=np.int8)
        return {"observation": obs, "action_mask": mask}

    def reset(self, seed: Optional[int] = None, options=None) -> None:
        seed = seed if seed is not None else self._seed
        self._rng = random.Random(seed)
        self.state_ = new_game(self.num_players_config, seed=seed)
        self.agents = self.possible_agents[:]
        self.rewards = {a: 0.0 for a in self.agents}
        self._cumulative_rewards = {a: 0.0 for a in self.agents}
        self.terminations = {a: False for a in self.agents}
        self.truncations = {a: False for a in self.agents}
        self.infos = {a: {} for a in self.agents}
        self._scores = self.state_.scores()
        self.agent_selection = self.agents[self.state_.current_player]

    def step(self, action: int) -> None:
        agent = self.agent_selection
        if self.terminations[agent] or self.truncations[agent]:
            self._was_dead_step(action)
            return
        self._cumulative_rewards[agent] = 0.0
        act = Action.from_action_id(int(action))
        _, round_result = step(self.state_, act)

        # Reward = score delta since this agent last acted; scoring only
        # actually changes at round resolution, matching real Azul.
        new_scores = self.state_.scores()
        for i, a in enumerate(self.agents):
            self.rewards[a] = float(new_scores[i] - self._scores[i])
        self._scores = new_scores

        if round_result is not None and round_result.game_over:
            winner = self.state_.winner()  # None = shared win
            for i, a in enumerate(self.agents):
                if winner is not None:
                    self.rewards[a] += 10.0 if i == winner else -10.0
                self.terminations[a] = True
        elif round_result is not None:
            deal_round(self.state_, self._rng)

        if not self.terminations[agent]:
            self.agent_selection = self.agents[self.state_.current_player]
        self._accumulate_rewards()


def env(**kwargs) -> AzulAECEnv:
    return AzulAECEnv(**kwargs)
