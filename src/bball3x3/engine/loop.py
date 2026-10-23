"""Minimal WS1 validation loop: heuristic-vs-heuristic full games.

This is a development harness, not the WS7 runner. It exercises the
resolution order from the spec (ball handler -> screens -> off-ball ->
contact -> rules -> fatigue -> invariants) through :class:`EngineSession`.
"""

from collections.abc import Callable

from bball3x3.agents.base import BasePlayer
from bball3x3.agents.heuristic_player import HeuristicPlayer
from bball3x3.config import SimulationConfig
from bball3x3.engine.session import (
    EngineSession,
    _clamp,
    _end_reason,
    _finished,
    _step_toward,
)
from bball3x3.referee import Referee, RuleBasedReferee
from bball3x3.schemas.state import GameState

__all__ = [
    "EngineSession",
    "play_heuristic_game",
    "_clamp",
    "_end_reason",
    "_finished",
    "_step_toward",
]


def play_heuristic_game(
    seed: int = 0,
    config: SimulationConfig | None = None,
    max_events: int = 2000,
    roster_path: str | None = None,
    start_state: GameState | None = None,
    agent_factory: Callable[[str], BasePlayer] | None = None,
    collect_history: bool = False,
    on_event: Callable[[dict], None] | None = None,
    referee: Referee | None = None,
) -> dict:
    """Play one full game (heuristic agents unless a factory is given).

    When ``on_event`` is supplied, the loop reports ``game_start`` once and
    one payload per completed transition. The payloads carry the raw and
    legalized proposals, the resolved event facts, any new violations, and a
    ``finished`` flag with ``end_reason``. The referee judges every
    transition; without an explicit referee the seedable rule referee is used.
    """
    session = EngineSession(
        seed=seed,
        config=config,
        roster_path=roster_path,
        start_state=start_state,
        referee=referee or RuleBasedReferee(seed=seed),
    )
    if on_event is not None:
        on_event(session.start_payload())

    if agent_factory is None:

        def agent_factory(pid: str) -> HeuristicPlayer:
            return HeuristicPlayer(pid, session.config)

    agents = {pid: agent_factory(pid) for pid in session.state.players}
    history: list[GameState] = []

    while session.events < max_events:
        if collect_history:
            history.append(session.state.model_copy(deep=True))
        proposals = {
            pid: agent.decide(session.state) for pid, agent in agents.items()
        }
        payload = session.step(proposals)
        if on_event is not None:
            on_event(payload)
        if session.finished:
            break

    if collect_history:
        history.append(session.state.model_copy(deep=True))

    return session.summary(history=history)
