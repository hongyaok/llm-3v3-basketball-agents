"""Minimal WS1 validation loop: heuristic-vs-heuristic full games.

This is a development harness, not the WS7 runner. It exercises the
resolution order from the spec (ball handler -> screens -> off-ball ->
contact -> rules -> fatigue -> invariants) so WS1 can close with
``heuristic full games, SIR = 0`` before the asyncio runner exists.
"""

from collections.abc import Callable, Mapping

from bball3x3.agents.base import BasePlayer
from bball3x3.agents.heuristic_player import HeuristicPlayer
from bball3x3.config import SimulationConfig, load_roster_config
from bball3x3.engine.abilities import build_abilities_map
from bball3x3.engine.actions import remap_invalid_action
from bball3x3.engine.clock import advance_action_clock, is_shot_clock_violation
from bball3x3.engine.conduct import collect_conduct_evidence
from bball3x3.engine.contact import build_referee_state, detect_contact, referee_query_text
from bball3x3.engine.court import ZONES, Court
from bball3x3.engine.invariants import collect_violations
from bball3x3.engine.movement import movement_label, speed_label
from bball3x3.engine.resolvers import (
    resolve_drive,
    resolve_free_throw,
    resolve_pass,
    resolve_rebound,
    resolve_screen,
    resolve_shot,
    update_fatigue,
)
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.rules import (
    apply_clear,
    apply_made_shot,
    apply_missed_shot,
    apply_rebound_winner,
    apply_referee_decision,
    apply_shot_clock_violation,
    apply_turnover,
    is_game_over,
    is_overtime_over,
    is_tied_at_expiry,
    other_team,
    start_overtime,
)
from bball3x3.engine.state import create_initial_state, set_ball_holder
from bball3x3.referee import Referee, RuleBasedReferee
from bball3x3.schemas.actions import ActionProposal, RemappedAction
from bball3x3.schemas.referee import OBJECTIVE_VIOLATIONS, RefereeDecision, RefereeState
from bball3x3.schemas.state import Abilities, GameState


def _clamp(pos: tuple[int, int], court: Court) -> tuple[int, int]:
    x = max(0, min(court.width_cells - 1, pos[0]))
    y = max(0, min(court.depth_cells - 1, pos[1]))
    return (x, y)


def _step_toward(
    pos: tuple[int, int], target: tuple[int, int], steps: int, court: Court
) -> tuple[int, int]:
    x, y = pos
    for _ in range(steps):
        if x != target[0]:
            x += 1 if target[0] > x else -1
        elif y != target[1]:
            y += 1 if target[1] > y else -1
        else:
            break
    return _clamp((x, y), court)


def _judge_referee_event(
    referee: Referee, ref_state: RefereeState,
) -> tuple[RefereeDecision, dict | None, str | None]:
    """Reject engine-owned calls before they can mutate game state."""
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
    if (call == "VIOLATION" and isinstance(violation, str)
            and violation in OBJECTIVE_VIOLATIONS):
        reason = "OBJECTIVE_VIOLATION"
    elif call != "NONE" and (
        event.get("objective_violation") is True
        or event.get("event_type") in OBJECTIVE_VIOLATIONS
    ):
        reason = "OBJECTIVE_EVENT"
    else:
        return RefereeDecision.model_validate(raw), None, None
    return RefereeDecision(), raw, reason


def _apply_referee_call(
    *,
    state: GameState,
    prev: GameState,
    event: dict,
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
            if decision.offender in state.players else state.offense
        )
        beneficiary = other_team(offender_team)
        if state.offense != beneficiary:
            apply_turnover(state, beneficiary, config)
        set_ball_holder(state, f"{beneficiary}1")
        state.shot_clock_s = config.rules.shot_clock_s
        reason = "REFEREE_VIOLATION"
        turnover = prev.offense == offender_team
    else:
        shot_value = (
            court.shot_value(state.players[fallback_shooter].pos)
            if fallback_shooter in state.players else 1
        )
        penalty = apply_referee_decision(
            state, decision, config,
            was_shooting=decision.foul_type == "SHOOTING_FOUL",
            shot_value=shot_value,
        )
        event["foul_called"] = True
        foul_team = penalty["foul_team"]
        beneficiary = other_team(foul_team)
        if state.offense != beneficiary:
            apply_turnover(state, beneficiary, config)
        shooter = decision.fouled_player
        if shooter not in state.players or state.players[shooter].team != beneficiary:
            shooter = fallback_shooter
        if shooter not in state.players or state.players[shooter].team != beneficiary:
            shooter = f"{beneficiary}1"
        set_ball_holder(state, shooter)

        # An offensive foul gives the ball to the other team without a bonus.
        free_throws = (
            0 if decision.foul_type == "OFFENSIVE_FOUL"
            else penalty["free_throws"]
        )
        retain_possession = penalty["retain_possession"]
        reason = "OFFENSIVE_FOUL" if decision.foul_type == "OFFENSIVE_FOUL" else "REFEREE_FOUL"
        turnover = decision.foul_type == "OFFENSIVE_FOUL" and prev.offense == foul_team
        if free_throws:
            points = 0
            last_made = False
            for _ in range(free_throws):
                ft, _, _ = resolve_free_throw(
                    shooter_id=shooter, abilities_map=abilities_map,
                    config=config, rng=rng, fatigue=state.players[shooter].fatigue,
                )
                last_made = ft["made"]
                points += int(last_made)
            if points:
                state.score[beneficiary] += points
                event.update(
                    scored=True, free_throw_team=beneficiary,
                    free_throw_points=points,
                )
            if not retain_possession:
                if last_made:
                    apply_turnover(state, foul_team, config)
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
    ``finished`` flag with ``end_reason``. The seedable rule referee judges
    every transition and its call is applied before the state is logged.
    """
    config = config or SimulationConfig()
    court = Court(config.court)
    rng = GameRNG.from_seed(seed)
    referee = referee or RuleBasedReferee(seed=seed)
    abilities_map: dict[str, Abilities] | None = None
    if roster_path is not None:
        try:
            abilities_map = build_abilities_map(load_roster_config(roster_path))
        except OSError:
            abilities_map = None

    state = start_state if start_state is not None else create_initial_state(config, rng)
    if on_event is not None:
        on_event(
            {
                "type": "game_start",
                "state": state,
                "seed": seed,
                "config": config,
                "roster_path": roster_path,
            }
        )
    if agent_factory is None:

        def agent_factory(pid: str) -> HeuristicPlayer:
            return HeuristicPlayer(pid, config)

    agents = {pid: agent_factory(pid) for pid in state.players}
    invalid = 0
    total_proposals = 0
    violations: list[dict] = []
    possessions = {state.offense: 1, other_team(state.offense): 0}
    shots_1pt_att = shots_1pt_made = 0
    shots_2pt_att = shots_2pt_made = 0
    screen_advantage = False
    after_drive = False
    after_pass = False
    ot_baseline: dict[str, int] | None = None
    events = 0
    history: list[GameState] = []

    while events < max_events:
        prev = state.model_copy(deep=True)
        if collect_history:
            history.append(prev)
        proposals: dict[str, ActionProposal] = {}
        legalized: dict[str, ActionProposal] = {}
        remaps: dict[str, RemappedAction | None] = {}
        for pid, agent in agents.items():
            raw = agent.decide(state)
            proposals[pid] = raw
            total_proposals += 1
            fixed, record = remap_invalid_action(state, raw)
            if record is not None:
                invalid += 1
            legalized[pid] = fixed
            remaps[pid] = record
        actions = {pid: p.action.upper() for pid, p in legalized.items()}

        # Loose ball: rebound lottery decides the next holder.
        if state.ball.status == "LOOSE":
            outcome, _, _ = resolve_rebound(
                state=state,
                abilities_map=abilities_map,
                court=court,
                config=config,
                rng=rng,
                actions=actions,
                offense_team=state.offense,
            )
            apply_rebound_winner(
                state, outcome["winner"], config, outcome["is_offensive"]
            )
            if not outcome["is_offensive"]:
                state.offense = outcome["team"]
            after_pass, after_drive, screen_advantage = False, False, False
            clock_res = advance_action_clock(state, "HOLD", config)
            update_fatigue(
                state=state,
                abilities_map=abilities_map,
                config=config,
                elapsed_s=clock_res.elapsed_s,
            )
            event = {
                "actions": actions,
                "elapsed_s": clock_res.elapsed_s,
                "rebound": True,
                "rebound_after_miss": True,
                "shot_clock_reset": True,
                "reset_reason": "OFFENSIVE_REBOUND"
                if outcome["is_offensive"]
                else "POSSESSION_CHANGE",
                "possession_changed": not outcome["is_offensive"],
                "possession_reason": None
                if outcome["is_offensive"]
                else "DEFENSIVE_REBOUND",
            }
            contact, _ = detect_contact(
                state=state, actions=actions, ball_handler_id=None,
                primary_defender_id=None, rebound_phase=True, rng=rng, config=config,
                action_targets={pid: proposal.target for pid, proposal in legalized.items()},
            )
            conduct_fields = collect_conduct_evidence(state, legalized, contact)
            if conduct_fields:
                event["conduct_evidence"] = conduct_fields["conduct_evidence"]
            state.event_idx = events + 1
            ref_state = build_referee_state(
                state=state, contact=contact,
                current_event={"event_type": "REBOUND", "actions": actions,
                               **conduct_fields},
            )
            referee_query = referee_query_text(ref_state)
            referee_decision, rejected_output, rejection_reason = _judge_referee_event(
                referee, ref_state,
            )
            _apply_referee_call(
                state=state, prev=prev, event=event, decision=referee_decision,
                config=config, court=court, rng=rng,
                abilities_map=abilities_map, fallback_shooter=outcome["winner"],
            )
            found = collect_violations(prev, state, event, court, config)
            violations.extend(found)
            if state.offense != prev.offense:
                possessions[state.offense] = possessions.get(state.offense, 0) + 1
            events += 1
            state.event_idx = events
            done = _finished(state, config, ot_baseline)
            if on_event is not None:
                on_event(
                    {
                        "type": "event",
                        "event_idx": events,
                        "prev": prev,
                        "state": state,
                        "proposals": proposals,
                        "legalized": legalized,
                        "remaps": remaps,
                        "actions": actions,
                        "event": event,
                        "new_violations": found,
                        "holder": None,
                        "handler_action": None,
                        "contact_detected": contact.contact_detected,
                        "referee_query": referee_query,
                        "referee_decision": referee_decision,
                        "referee_rejected_output": rejected_output,
                        "referee_rejection_reason": rejection_reason,
                        "referee_trace": getattr(referee, "last_result", None),
                        "rebound": True,
                        "finished": done,
                        "end_reason": _end_reason(state, config) if done else None,
                    }
                )
            if _finished(state, config, ot_baseline):
                break
            continue

        holder = next(
            (pid for pid, p in state.players.items() if p.has_ball), None
        )
        if holder is None:
            set_ball_holder(state, f"{state.offense}1")
            holder = state.players[state.ball.holder or f"{state.offense}1"].id
        handler_action = actions.get(holder, "HOLD")
        primary = next(
            (
                d
                for d, m in state.matchups.items()
                if m == holder and state.players[d].team != state.players[holder].team
            ),
            None,
        )
        help_present = any(
            actions.get(pid) in ("HELP_PAINT", "DOUBLE_TEAM")
            for pid, p in state.players.items()
            if p.team != state.players[holder].team
        )
        defender_actions = {
            pid: a
            for pid, a in actions.items()
            if state.players[pid].team != state.players[holder].team
        }
        event: dict = {"actions": actions, "possession_changed": False}
        elapsed = 1.0

        if handler_action == "SHOOT" and not state.needs_clear:
            outcome, _, _ = resolve_shot(
                state=state,
                shooter_id=holder,
                abilities_map=abilities_map,
                court=court,
                config=config,
                rng=rng,
                defender_actions=defender_actions,
                help_present=help_present,
                after_drive_success=after_drive,
                after_pass_reception=after_pass,
                screen_advantage=screen_advantage,
            )
            shot_value = court.shot_value(state.players[holder].pos)
            if shot_value == 2:
                shots_2pt_att += 1
                shots_2pt_made += 1 if outcome["made"] else 0
            else:
                shots_1pt_att += 1
                shots_1pt_made += 1 if outcome["made"] else 0
            if outcome["made"]:
                scoring = state.offense
                points = outcome["points"]
                apply_made_shot(state, scoring, points, config)
                event.update(
                    {
                        "scored": True,
                        "points": points,
                        "scoring_team": scoring,
                        "possession_changed": True,
                        "possession_reason": "MADE_BASKET",
                        "shot_clock_reset": True,
                        "reset_reason": "POSSESSION_CHANGE",
                    }
                )
                set_ball_holder(state, f"{state.offense}1")
                state.needs_clear = True
            else:
                apply_missed_shot(state)
                event.update({"scored": False, "rebound_after_miss": True})
            elapsed = 1.0
            after_drive, after_pass, screen_advantage = False, False, False
        elif handler_action == "PASS":
            target = legalized[holder].target
            mates = [
                pid
                for pid, p in state.players.items()
                if p.team == state.offense and pid != holder
            ]
            if target not in mates:
                target = mates[0] if mates else None
            if target is None:
                elapsed = 1.0
            else:
                outcome, _, _ = resolve_pass(
                    state=state,
                    passer_id=holder,
                    target_id=target,
                    abilities_map=abilities_map,
                    court=court,
                    config=config,
                    rng=rng,
                )
                if outcome["completed"]:
                    set_ball_holder(state, target)
                    after_pass = True
                    after_drive, screen_advantage = False, False
                elif outcome.get("steal_by"):
                    thief = outcome["steal_by"]
                    apply_turnover(state, state.players[thief].team, config)
                    set_ball_holder(state, thief)
                    state.needs_clear = True
                    event.update(
                        {
                            "possession_changed": True,
                            "possession_reason": "STEAL",
                            "turnover": True,
                            "shot_clock_reset": True,
                            "reset_reason": "POSSESSION_CHANGE",
                        }
                    )
                    after_pass, after_drive, screen_advantage = False, False, False
                else:
                    apply_turnover(state, other_team(state.offense), config)
                    set_ball_holder(state, f"{state.offense}1")
                    state.needs_clear = True
                    event.update(
                        {
                            "possession_changed": True,
                            "possession_reason": "OOB_TURNOVER",
                            "turnover": True,
                            "shot_clock_reset": True,
                            "reset_reason": "POSSESSION_CHANGE",
                        }
                    )
                    after_pass, after_drive, screen_advantage = False, False, False
                elapsed = 1.0
        elif handler_action == "DRIVE":
            outcome, _, _ = resolve_drive(
                ball_handler_id=holder,
                primary_defender_id=primary,
                help_present=help_present,
                abilities_map=abilities_map,
                config=config,
                rng=rng,
            )
            if outcome["success"]:
                pos = state.players[holder].pos
                new_pos = _step_toward(pos, court.basket, 2, court)
                state.players[holder].prev_pos = pos
                state.players[holder].pos = new_pos
                state.ball.pos = new_pos
                after_drive = True
                after_pass, screen_advantage = False, False
            elif outcome.get("stripped"):
                thief = primary or other_team(state.offense) + "1"
                apply_turnover(state, state.players[thief].team, config)
                set_ball_holder(state, thief)
                state.needs_clear = True
                event.update(
                    {
                        "possession_changed": True,
                        "possession_reason": "STRIP",
                        "turnover": True,
                        "shot_clock_reset": True,
                        "reset_reason": "POSSESSION_CHANGE",
                    }
                )
                after_drive, after_pass, screen_advantage = False, False, False
            elapsed = 2.0
        elif handler_action == "CLEAR":
            apply_clear(state, holder, court, config)
            elapsed = 2.0
        else:
            elapsed = 1.0
            after_pass = False

        # Screens resolve before off-ball movement (spec order step 2-3).
        for pid, act in actions.items():
            if act == "SCREEN" and pid != holder:
                outcome, _, _ = resolve_screen(screener_id=pid, rng=rng)
                if outcome["success"]:
                    screen_advantage = True

        # Minimal off-ball drift so movement invariants are exercised.
        for pid, act in actions.items():
            if state.players[pid].has_ball:
                continue
            if state.players[pid].team != state.offense:
                continue
            if act in ("CUT", "CUT_BASELINE", "ROLL", "MOVE"):
                pos = state.players[pid].pos
                state.players[pid].prev_pos = pos
                state.players[pid].pos = _step_toward(pos, court.basket, 1, court)
            elif act == "POP":
                # Pick-and-pop: one step away from the basket for spacing.
                pos = state.players[pid].pos
                away = (
                    2 * pos[0] - court.basket[0],
                    2 * pos[1] - court.basket[1],
                )
                state.players[pid].prev_pos = pos
                state.players[pid].pos = _step_toward(pos, away, 1, court)
            elif act == "SPOT_UP":
                state.players[pid].prev_pos = state.players[pid].pos

        # The ball follows whoever holds it after passes and turnovers.
        if state.ball.status == "HELD" and state.ball.holder in state.players:
            state.ball.pos = state.players[state.ball.holder].pos

        # Defensive rotation: defenders step toward their assignment, so
        # openness reflects pressure instead of frozen starting spots.
        # Targets use previous positions: within one event, no defender
        # sees where the offense moved this event (no peeking).
        current_holder = (
            state.ball.holder if state.ball.status == "HELD" else None
        )
        for pid, act in actions.items():
            player = state.players[pid]
            if player.has_ball or player.team == state.offense:
                continue
            if act in (
                "DEFEND",
                "CONTEST",
                "STEAL_ATTEMPT",
                "DENY",
                "DOUBLE_TEAM",
                "SWITCH",
            ):
                matchup = state.matchups.get(pid)
                if matchup in state.players:
                    target = state.players[matchup].prev_pos
                elif current_holder in state.players:
                    target = state.players[current_holder].prev_pos
                else:
                    target = None
            elif act == "HELP_PAINT":
                target = ZONES["PAINT"]
            else:
                target = None
            if target is not None and player.pos != target:
                player.prev_pos = player.pos
                player.pos = _step_toward(player.pos, target, 1, court)

        for pid, player in state.players.items():
            player.movement = movement_label(player.prev_pos, player.pos)
            player.speed = speed_label(player.prev_pos, player.pos, elapsed)

        contact, _ = detect_contact(
            state=state,
            actions=actions,
            ball_handler_id=holder,
            primary_defender_id=primary,
            action_targets={pid: proposal.target for pid, proposal in legalized.items()},
            rebound_phase=False,
            rng=rng,
            config=config,
        )
        clock_res = advance_action_clock(state, handler_action, config)
        update_fatigue(
            state=state,
            abilities_map=abilities_map,
            config=config,
            elapsed_s=clock_res.elapsed_s,
        )
        event["elapsed_s"] = clock_res.elapsed_s

        state.event_idx = events + 1
        conduct_fields = collect_conduct_evidence(state, legalized, contact)
        if conduct_fields:
            event["conduct_evidence"] = conduct_fields["conduct_evidence"]
        ref_state = build_referee_state(
            state=state,
            contact=contact,
            current_event={
                "event_type": "SHOT_CLOCK" if is_shot_clock_violation(state)
                else handler_action,
                "actions": actions,
                "objective_violation": bool(event.get("possession_changed")),
                "was_shooting": handler_action == "SHOOT",
                **conduct_fields,
            },
        )
        referee_query = referee_query_text(ref_state)
        referee_decision, rejected_output, rejection_reason = _judge_referee_event(
            referee, ref_state,
        )
        _apply_referee_call(
            state=state, prev=prev, event=event, decision=referee_decision,
            config=config, court=court, rng=rng,
            abilities_map=abilities_map, fallback_shooter=holder,
        )

        if referee_decision.call == "NONE" and is_shot_clock_violation(state):
            apply_shot_clock_violation(state, config)
            set_ball_holder(state, f"{state.offense}1")
            state.needs_clear = True
            event.update(
                {
                    "possession_changed": True,
                    "possession_reason": "SHOT_CLOCK",
                    "turnover": True,
                    "shot_clock_reset": True,
                    "reset_reason": "POSSESSION_CHANGE",
                }
            )

        found = collect_violations(prev, state, event, court, config)
        violations.extend(found)
        if state.offense != prev.offense:
            possessions[state.offense] = possessions.get(state.offense, 0) + 1
        events += 1
        state.event_idx = events
        done = _finished(state, config, ot_baseline)
        if on_event is not None:
            on_event(
                {
                    "type": "event",
                    "event_idx": events,
                    "prev": prev,
                    "state": state,
                    "proposals": proposals,
                    "legalized": legalized,
                    "remaps": remaps,
                    "actions": actions,
                    "event": event,
                    "new_violations": found,
                    "holder": holder,
                    "handler_action": handler_action,
                    "contact_detected": bool(contact.contact_detected),
                    "referee_query": referee_query,
                    "referee_decision": referee_decision,
                    "referee_rejected_output": rejected_output,
                    "referee_rejection_reason": rejection_reason,
                    "referee_trace": getattr(referee, "last_result", None),
                    "rebound": False,
                    "finished": done,
                    "end_reason": _end_reason(state, config) if done else None,
                }
            )

        if state.phase == "LIVE" and is_tied_at_expiry(state):
            ot_baseline = start_overtime(state, config)
            continue
        if _finished(state, config, ot_baseline):
            break

    if collect_history:
        history.append(state.model_copy(deep=True))

    return {
        "events": events,
        "score": dict(state.score),
        "phase": state.phase,
        "violations": violations,
        "sivr": len(violations) / max(events, 1),
        "invalid_actions": invalid,
        "total_proposals": total_proposals,
        "iar": invalid / max(total_proposals, 1),
        "possessions": dict(possessions),
        "shots_1pt": {"att": shots_1pt_att, "made": shots_1pt_made},
        "shots_2pt": {"att": shots_2pt_att, "made": shots_2pt_made},
        "overtime_reached": ot_baseline is not None,
        "history": history,
        "final_state": state,
    }


def _end_reason(state, config: SimulationConfig) -> str:
    """Classify a finished game for the terminal resolution record."""
    if state.phase == "OT":
        return "OT_WIN"
    if max(state.score.values()) >= config.rules.win_score:
        return "WIN_SCORE"
    return "CLOCK_EXPIRED"


def _finished(
    state, config: SimulationConfig, ot_baseline: dict[str, int] | None
) -> bool:
    if state.phase == "OT" and ot_baseline is not None:
        return is_overtime_over(state, config, ot_baseline)
    return is_game_over(state, config)
