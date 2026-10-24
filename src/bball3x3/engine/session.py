"""Synchronous engine session extracted from loop.py (WS3 §3.6 & §3.8).

Both ``play_heuristic_game`` and the async LLM runner drive the engine through
:class:`EngineSession` so resolution order, RNG draws, and state transitions
have a single source of truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bball3x3.referee import Referee

from bball3x3.config import SimulationConfig, load_roster_config
from bball3x3.engine.abilities import build_abilities_map
from bball3x3.engine.actions import DRIVE_DIRECTIONS, remap_invalid_action
from bball3x3.engine.clock import advance_action_clock, is_shot_clock_violation
from bball3x3.engine.conduct import collect_conduct_evidence
from bball3x3.engine.contact import build_referee_state, detect_contact, referee_query_text
from bball3x3.engine.court import ZONES, Court
from bball3x3.engine.invariants import collect_violations
from bball3x3.engine.movement import movement_label, speed_label
from bball3x3.engine.referee_bridge import apply_referee_call, judge_referee_event
from bball3x3.engine.resolvers import (
    resolve_drive,
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
    apply_shot_clock_violation,
    apply_turnover,
    is_game_over,
    is_overtime_over,
    is_tied_at_expiry,
    other_team,
    start_overtime,
)
from bball3x3.engine.state import create_initial_state, set_ball_holder
from bball3x3.schemas.actions import ActionProposal, RemappedAction
from bball3x3.schemas.referee import RefereeDecision
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


def _drive_target_cell(direction: str | None, court: Court) -> tuple[int, int]:
    """Return the target coordinate for a DRIVE action with an optional direction."""
    bx, by = court.basket
    if direction is None:
        return (bx, by)
    d = direction.upper()
    if d == "LEFT":
        return (_clamp((bx - 2, by), court))
    if d == "RIGHT":
        return (_clamp((bx + 2, by), court))
    if d == "BASELINE":
        return (_clamp((bx, 0), court))
    # MIDDLE or fallback
    return (bx, by)


def _end_reason(state: GameState, config: SimulationConfig) -> str:
    """Classify a finished game for the terminal resolution record."""
    if state.phase == "OT":
        return "OT_WIN"
    if max(state.score.values()) >= config.rules.win_score:
        return "WIN_SCORE"
    return "CLOCK_EXPIRED"


def _finished(
    state: GameState, config: SimulationConfig, ot_baseline: dict[str, int] | None
) -> bool:
    if state.phase == "OT" and ot_baseline is not None:
        return is_overtime_over(state, config, ot_baseline)
    return is_game_over(state, config)


class EngineSession:
    """Stateful single-game engine session advancing one decision event at a time."""

    def __init__(
        self,
        *,
        seed: int = 0,
        config: SimulationConfig | None = None,
        roster_path: str | None = None,
        abilities_map: dict[str, Abilities] | None = None,
        start_state: GameState | None = None,
        referee: Referee | None = None,
        first_possession: str | None = None,
    ) -> None:
        self.seed = seed
        self.config = config or SimulationConfig()
        self.roster_path = roster_path
        self.court = Court(self.config.court)
        self.rng = GameRNG.from_seed(seed)
        self.referee = referee

        if abilities_map is not None:
            self.abilities_map: dict[str, Abilities] | None = abilities_map
        elif roster_path is not None:
            try:
                self.abilities_map = build_abilities_map(load_roster_config(roster_path))
            except OSError:
                self.abilities_map = None
        else:
            self.abilities_map = None

        # first_possession None keeps the seeded coin flip
        self.state: GameState = (
            start_state
            if start_state is not None
            else create_initial_state(self.config, self.rng, first_possession)
        )
        self.invalid = 0
        self.total_proposals = 0
        self.violations: list[dict[str, Any]] = []
        self.possessions: dict[str, int] = {
            self.state.offense: 1,
            other_team(self.state.offense): 0,
        }
        self.shots_1pt_att = 0
        self.shots_1pt_made = 0
        self.shots_2pt_att = 0
        self.shots_2pt_made = 0
        self.screen_advantage = False
        self.after_drive = False
        self.after_pass = False
        self.ot_baseline: dict[str, int] | None = None
        self.events = 0
        self.finished = False
        self.end_reason: str | None = None

    def start_payload(self) -> dict[str, Any]:
        return {
            "type": "game_start",
            "state": self.state,
            "seed": self.seed,
            "config": self.config,
            "roster_path": self.roster_path,
        }

    def step(self, proposals: dict[str, ActionProposal]) -> dict[str, Any]:
        """Legalize proposals, resolve one decision event, and return the event payload."""
        state = self.state
        config = self.config
        court = self.court
        rng = self.rng
        abilities_map = self.abilities_map

        prev = state.model_copy(deep=True)
        legalized: dict[str, ActionProposal] = {}
        remaps: dict[str, RemappedAction | None] = {}

        for pid, raw in proposals.items():
            self.total_proposals += 1
            fixed, record = remap_invalid_action(state, raw)
            if record is not None:
                self.invalid += 1
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
            self.after_pass, self.after_drive, self.screen_advantage = False, False, False
            clock_res = advance_action_clock(state, "HOLD", config)
            update_fatigue(
                state=state,
                abilities_map=abilities_map,
                config=config,
                elapsed_s=clock_res.elapsed_s,
            )
            event: dict[str, Any] = {
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
                state=state,
                actions=actions,
                ball_handler_id=None,
                primary_defender_id=None,
                action_targets={
                    pid: proposal.target for pid, proposal in legalized.items()
                },
                rebound_phase=True,
                rng=rng,
                config=config,
            )
            conduct_fields = collect_conduct_evidence(state, legalized, contact)
            if conduct_fields:
                event["conduct_evidence"] = conduct_fields["conduct_evidence"]
            state.event_idx = self.events + 1
            ref_state = build_referee_state(
                state=state,
                contact=contact,
                current_event={
                    "event_type": "REBOUND",
                    "actions": actions,
                    **conduct_fields,
                },
            )
            referee_query = referee_query_text(ref_state)
            if self.referee is not None:
                referee_decision, rejected_output, rejection_reason = (
                    judge_referee_event(self.referee, ref_state)
                )
                apply_referee_call(
                    state=state,
                    prev=prev,
                    event=event,
                    decision=referee_decision,
                    config=config,
                    court=court,
                    rng=rng,
                    abilities_map=abilities_map,
                    fallback_shooter=outcome["winner"],
                )
                referee_trace = getattr(self.referee, "last_result", None)
            else:
                referee_decision = RefereeDecision()
                rejected_output = None
                rejection_reason = None
                referee_trace = None
            found = collect_violations(prev, state, event, court, config)
            self.violations.extend(found)
            if state.offense != prev.offense:
                self.possessions[state.offense] = self.possessions.get(state.offense, 0) + 1
            self.events += 1
            state.event_idx = self.events
            done = _finished(state, config, self.ot_baseline)
            self.finished = done
            self.end_reason = _end_reason(state, config) if done else None
            return {
                "type": "event",
                "event_idx": self.events,
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
                "contact_detected": bool(contact.contact_detected),
                "referee_query": referee_query,
                "referee_decision": referee_decision,
                "referee_rejected_output": rejected_output,
                "referee_rejection_reason": rejection_reason,
                "referee_trace": referee_trace,
                "rebound": True,
                "finished": done,
                "end_reason": self.end_reason,
            }

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
        event = {"actions": actions, "possession_changed": False}
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
                after_drive_success=self.after_drive,
                after_pass_reception=self.after_pass,
                screen_advantage=self.screen_advantage,
            )
            shot_value = court.shot_value(state.players[holder].pos)
            if shot_value == 2:
                self.shots_2pt_att += 1
                self.shots_2pt_made += 1 if outcome["made"] else 0
            else:
                self.shots_1pt_att += 1
                self.shots_1pt_made += 1 if outcome["made"] else 0
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
            self.after_drive, self.after_pass, self.screen_advantage = False, False, False
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
                    self.after_pass = True
                    self.after_drive, self.screen_advantage = False, False
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
                    self.after_pass, self.after_drive, self.screen_advantage = False, False, False
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
                    self.after_pass, self.after_drive, self.screen_advantage = False, False, False
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
                drive_dir = legalized[holder].target
                drive_goal = (
                    _drive_target_cell(drive_dir, court)
                    if drive_dir in DRIVE_DIRECTIONS
                    else court.basket
                )
                new_pos = _step_toward(pos, drive_goal, 2, court)
                state.players[holder].prev_pos = pos
                state.players[holder].pos = new_pos
                state.ball.pos = new_pos
                self.after_drive = True
                self.after_pass, self.screen_advantage = False, False
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
                self.after_drive, self.after_pass, self.screen_advantage = False, False, False
            elapsed = 2.0
        elif handler_action == "CLEAR":
            apply_clear(state, holder, court, config)
            elapsed = 2.0
        elif handler_action in ("DRIBBLE_MOVE", "POST_UP"):
            zone_target = legalized[holder].target
            if zone_target and zone_target in ZONES:
                pos = state.players[holder].pos
                new_pos = _step_toward(pos, ZONES[zone_target], 1, court)
                state.players[holder].prev_pos = pos
                state.players[holder].pos = new_pos
                state.ball.pos = new_pos
            elapsed = 1.0
            self.after_pass = False
        else:
            elapsed = 1.0
            self.after_pass = False

        # Screens resolve before off-ball movement (spec order step 2-3).
        for pid, act in actions.items():
            if act == "SCREEN" and pid != holder:
                outcome, _, _ = resolve_screen(screener_id=pid, rng=rng)
                if outcome["success"]:
                    self.screen_advantage = True

        # Off-ball movement: zone target steps toward the zone cell; otherwise default drift.
        for pid, act in actions.items():
            if state.players[pid].has_ball:
                continue
            if state.players[pid].team != state.offense:
                continue
            target_zone = legalized[pid].target
            if act in ("CUT", "CUT_BASELINE", "ROLL", "MOVE", "POP", "SPOT_UP", "GET_BACK") and (
                target_zone and target_zone in ZONES
            ):
                pos = state.players[pid].pos
                state.players[pid].prev_pos = pos
                state.players[pid].pos = _step_toward(pos, ZONES[target_zone], 1, court)
            elif act in ("CUT", "CUT_BASELINE", "ROLL", "MOVE"):
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

        # Defensive rotation: defenders step toward their assignment or explicit target.
        current_holder = (
            state.ball.holder if state.ball.status == "HELD" else None
        )
        for pid, act in actions.items():
            player = state.players[pid]
            if player.has_ball or player.team == state.offense:
                continue
            explicit_target = legalized[pid].target
            if act in ("MOVE", "GET_BACK") and explicit_target in ZONES:
                target_pos: tuple[int, int] | None = ZONES[explicit_target]
            elif act in (
                "DEFEND",
                "CONTEST",
                "STEAL_ATTEMPT",
                "DENY",
                "DOUBLE_TEAM",
                "SWITCH",
            ):
                if (
                    act in ("DEFEND", "CONTEST", "STEAL_ATTEMPT")
                    and explicit_target in state.players
                    and state.players[explicit_target].team != player.team
                ):
                    target_pos = state.players[explicit_target].prev_pos
                else:
                    matchup = state.matchups.get(pid)
                    if matchup in state.players:
                        target_pos = state.players[matchup].prev_pos
                    elif current_holder in state.players:
                        target_pos = state.players[current_holder].prev_pos
                    else:
                        target_pos = None
            elif act == "HELP_PAINT":
                target_pos = ZONES["PAINT"]
            else:
                target_pos = None
            if target_pos is not None and player.pos != target_pos:
                player.prev_pos = player.pos
                player.pos = _step_toward(player.pos, target_pos, 1, court)

        for pid, player in state.players.items():
            player.movement = movement_label(player.prev_pos, player.pos)
            player.speed = speed_label(player.prev_pos, player.pos, elapsed)

        contact, _ = detect_contact(
            state=state,
            actions=actions,
            ball_handler_id=holder,
            primary_defender_id=primary,
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

        state.event_idx = self.events + 1
        conduct_fields = collect_conduct_evidence(state, legalized, contact)
        if conduct_fields:
            event["conduct_evidence"] = conduct_fields["conduct_evidence"]
        ref_state = build_referee_state(
            state=state,
            contact=contact,
            current_event={
                "event_type": "SHOT_CLOCK"
                if is_shot_clock_violation(state)
                else handler_action,
                "actions": actions,
                "objective_violation": bool(event.get("possession_changed")),
                "was_shooting": handler_action == "SHOOT",
                **conduct_fields,
            },
        )
        referee_query = referee_query_text(ref_state)
        if self.referee is not None:
            referee_decision, rejected_output, rejection_reason = judge_referee_event(
                self.referee, ref_state
            )
            apply_referee_call(
                state=state,
                prev=prev,
                event=event,
                decision=referee_decision,
                config=config,
                court=court,
                rng=rng,
                abilities_map=abilities_map,
                fallback_shooter=holder,
            )
            referee_trace = getattr(self.referee, "last_result", None)
        else:
            referee_decision = RefereeDecision()
            rejected_output = None
            rejection_reason = None
            referee_trace = None

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
        self.violations.extend(found)
        if state.offense != prev.offense:
            self.possessions[state.offense] = self.possessions.get(state.offense, 0) + 1
        self.events += 1
        state.event_idx = self.events
        done = _finished(state, config, self.ot_baseline)

        tied_expiry = state.phase == "LIVE" and is_tied_at_expiry(state)
        state_for_payload = state.model_copy(deep=True) if tied_expiry else state

        payload = {
            "type": "event",
            "event_idx": self.events,
            "prev": prev,
            "state": state_for_payload,
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
            "referee_trace": referee_trace,
            "rebound": False,
            "finished": done,
            "end_reason": _end_reason(state_for_payload, config) if done else None,
        }

        if tied_expiry:
            self.ot_baseline = start_overtime(state, config)
        self.finished = _finished(state, config, self.ot_baseline) and not tied_expiry
        self.end_reason = payload["end_reason"]
        return payload

    def summary(self, history: list[GameState] | None = None) -> dict[str, Any]:
        return {
            "events": self.events,
            "score": dict(self.state.score),
            "phase": self.state.phase,
            "violations": self.violations,
            "sivr": len(self.violations) / max(self.events, 1),
            "invalid_actions": self.invalid,
            "total_proposals": self.total_proposals,
            "iar": self.invalid / max(self.total_proposals, 1),
            "possessions": dict(self.possessions),
            "shots_1pt": {"att": self.shots_1pt_att, "made": self.shots_1pt_made},
            "shots_2pt": {"att": self.shots_2pt_att, "made": self.shots_2pt_made},
            "overtime_reached": self.ot_baseline is not None,
            "history": history if history is not None else [],
            "final_state": self.state,
        }
