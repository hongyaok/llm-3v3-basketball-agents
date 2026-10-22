"""Uniform-random baseline for fuzzing (WS1/WS3)."""

import numpy as np

from bball3x3.agents.base import BasePlayer, opponents, teammates
from bball3x3.engine.actions import (
    DRIVE_DIRECTIONS,
    TARGET_PLAYER_ACTIONS,
    ZONE_TARGET_ACTIONS,
    get_legal_actions,
)
from bball3x3.engine.court import ZONES
from bball3x3.schemas.actions import ActionProposal
from bball3x3.schemas.state import GameState

_SORTED_ZONES = sorted(ZONES)


class RandomPlayer(BasePlayer):
    """Pick uniformly from legal actions. Own RNG so fuzzing is reproducible."""

    def __init__(self, player_id: str, seed: int = 0):
        super().__init__(player_id)
        self._rng = np.random.default_rng(seed + hash(player_id) % (2**31))

    def decide(self, state: GameState, **kwargs) -> ActionProposal:
        _ = kwargs
        try:
            legal = sorted(get_legal_actions(state, self.player_id))
        except ValueError:
            return ActionProposal(player_id=self.player_id, action="HOLD")
        if not legal:
            return ActionProposal(player_id=self.player_id, action="HOLD")
        action = str(self._rng.choice(legal))
        target = None
        if action in TARGET_PLAYER_ACTIONS:
            target = self._random_target(state, action)
            if target is None:
                return ActionProposal(player_id=self.player_id, action="HOLD")
        elif action in ZONE_TARGET_ACTIONS:
            if bool(self._rng.integers(0, 2)):
                target = str(self._rng.choice(_SORTED_ZONES))
        elif action == "DRIVE":
            if bool(self._rng.integers(0, 2)):
                target = str(self._rng.choice(DRIVE_DIRECTIONS))
        return ActionProposal(
            player_id=self.player_id, action=action, target=target
        )

    def _random_target(self, state: GameState, action: str) -> str | None:
        if action in ("PASS", "SWITCH"):
            options = teammates(state, self.player_id)
        elif action == "SCREEN":
            options = teammates(state, self.player_id) + opponents(state, self.player_id)
        elif action in ("DOUBLE_TEAM", "DENY"):
            options = opponents(state, self.player_id)
        else:
            options = []
        if not options:
            return None
        return str(self._rng.choice(sorted(options)))
