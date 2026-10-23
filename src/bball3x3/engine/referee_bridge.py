"""Shared referee bridge: judge once, apply through the engine only (WS1/WS5).

Both :class:`EngineSession` and the heuristic loop use these two helpers so
the sync heuristic path and the async LLM path share identical guard and
application semantics. The referee returns a ruling; only the engine mutates
score, clock, possession, fouls and free throws.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bball3x3.config import SimulationConfig
from bball3x3.engine.court import Court
from bball3x3.engine.resolvers import resolve_free_throw
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.rules import apply_missed_shot, apply_referee_decision, apply_turnover
from bball3x3.engine.state import set_ball_holder
from bball3x3.referee import Referee
from bball3x3.schemas.referee import OBJECTIVE_VIOLATIONS, RefereeDecision, RefereeState
from bball3x3.schemas.state import Abilities, GameState


def judge_referee_event(
    referee: Referee, ref_state: RefereeState
) -> tuple[RefereeDecision, dict[str, Any] | None, str | None]:
    """Judge one resolved state; reject engine-owned calls before mutation."""
    proposed = referee.judge(ref_state)
    if isinstance(proposed, RefereeDecision):
        raw = proposed.model_dump(warnings=False)
    elif isinstance(proposed, Mapping):
        raw = dict(proposed)
    else:
        raise TypeError("Referee.judge() must return a RefereeDecision or mapping")
    event = ref_state.current_event
    call = raw.get("call")
    violation = raw.get("violation_type")
    if (
        call == "VIOLATION"
        and isinstance(violation, str)
        and violation in OBJECTIVE_VIOLATIONS
    ):
        reason = "OBJECTIVE_VIOLATION"
    elif call != "NONE" and (
        event.get("objective_violation") is True
        or event.get("event_type") in OBJECTIVE_VIOLATIONS
    ):
        reason = "OBJECTIVE_EVENT"
    else:
        return RefereeDecision.model_validate(raw), None, None
    return RefereeDecision(), raw, reason


def apply_referee_call(
    *,
    state: GameState,
    prev: GameState,
    event: dict[str, Any],
    decision: RefereeDecision,
    config: SimulationConfig,
    court: Court,
    rng: GameRNG,
    abilities_map: dict[str, Abilities] | None,
    fallback_shooter: str | None,
) -> None:
    """Apply the judged call and describe the final transition for logging."""
    if decision.call == "NONE":
        return

    if decision.call == "VIOLATION":
        offender_team = (
            state.players[decision.offender].team
            if decision.offender in state.players
            else state.offense
        )
        beneficiary = "B" if offender_team == "A" else "A"
        if state.offense != beneficiary:
            apply_turnover(state, beneficiary, config)  # type: ignore[arg-type]
        set_ball_holder(state, f"{beneficiary}1")
        state.shot_clock_s = config.rules.shot_clock_s
        reason = "REFEREE_VIOLATION"
        turnover = prev.offense == offender_team
    else:
        shot_value = (
            court.shot_value(state.players[fallback_shooter].pos)
            if fallback_shooter in state.players
            else 1
        )
        penalty = apply_referee_decision(
            state,
            decision,
            config,
            was_shooting=decision.foul_type == "SHOOTING_FOUL",
            shot_value=shot_value,
        )
        event["foul_called"] = True
        foul_team = penalty["foul_team"]
        beneficiary = "B" if foul_team == "A" else "A"
        if state.offense != beneficiary:
            apply_turnover(state, beneficiary, config)  # type: ignore[arg-type]
        shooter = decision.fouled_player
        if shooter not in state.players or state.players[shooter].team != beneficiary:
            shooter = fallback_shooter
        if shooter not in state.players or state.players[shooter].team != beneficiary:
            shooter = f"{beneficiary}1"
        set_ball_holder(state, shooter)

        free_throws = (
            0 if decision.foul_type == "OFFENSIVE_FOUL" else penalty["free_throws"]
        )
        retain_possession = penalty["retain_possession"]
        reason = (
            "OFFENSIVE_FOUL"
            if decision.foul_type == "OFFENSIVE_FOUL"
            else "REFEREE_FOUL"
        )
        turnover = decision.foul_type == "OFFENSIVE_FOUL" and prev.offense == foul_team
        if free_throws:
            points = 0
            last_made = False
            for _ in range(free_throws):
                ft, _, _ = resolve_free_throw(
                    shooter_id=shooter,
                    abilities_map=abilities_map,
                    config=config,
                    rng=rng,
                    fatigue=state.players[shooter].fatigue,
                )
                last_made = ft["made"]
                points += int(last_made)
            if points:
                state.score[beneficiary] += points
                event.update(
                    scored=True,
                    free_throw_team=beneficiary,
                    free_throw_points=points,
                )
            if not retain_possession:
                if last_made:
                    apply_turnover(state, foul_team, config)  # type: ignore[arg-type]
                    set_ball_holder(state, f"{foul_team}1")
                    reason = "FREE_THROW_MADE"
                else:
                    apply_missed_shot(state)
                    event["rebound_after_miss"] = True
        if state.ball.status == "HELD":
            state.shot_clock_s = config.rules.shot_clock_s

    changed = state.offense != prev.offense
    event["possession_changed"] = changed
    event["possession_reason"] = reason if changed else None
    event["turnover"] = turnover and changed
    event["shot_clock_reset"] = True
    event["reset_reason"] = "POSSESSION_CHANGE" if changed else "CHECK_BALL"
