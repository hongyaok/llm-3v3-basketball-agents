"""Observation builder and Code 1 text renderer (WS3 §3.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from bball3x3.agents.context import CoordinationView, NullCoordinationView
from bball3x3.agents.xml_io import render_message
from bball3x3.engine.actions import format_legal_action_hint, get_legal_actions
from bball3x3.memory.personal import PersonalMemory
from bball3x3.schemas.agent import CoordinationConfig
from bball3x3.schemas.memory import CSEntry, MemoryEntry
from bball3x3.schemas.messages import CaptainCall, Message
from bball3x3.schemas.state import GameState

PlayerRole = Literal["BALL_HANDLER", "OFF_BALL", "DEFENSE", "REBOUND"]


class PeerObservation(BaseModel):
    player_id: str
    pos: tuple[int, int]
    movement: str
    speed: str
    has_ball: bool = False


class Observation(BaseModel):
    """Structured per-player observation prior to rendering into Code 1 text."""

    player_id: str
    team: Literal["A", "B"]
    is_captain: bool = False
    role: PlayerRole
    pos: tuple[int, int]
    has_ball: bool
    fatigue: float

    teammates: list[PeerObservation] = Field(default_factory=list)
    opponents: list[PeerObservation] = Field(default_factory=list)
    matchups: list[tuple[str, str]] = Field(default_factory=list)

    ball_pos: tuple[int, int]
    ball_status: str
    ball_holder: str | None = None
    offense_team: Literal["A", "B"]

    event_idx: int
    score: dict[str, int]
    game_clock_s: float
    shot_clock_s: float
    team_fouls: dict[str, int]
    phase: str
    flags: list[str] = Field(default_factory=list)

    legal_actions: list[str] = Field(default_factory=list)
    legal_action_hints: list[str] = Field(default_factory=list)

    coordination_flags: CoordinationConfig = Field(default_factory=CoordinationConfig)
    previous_captain_call: CaptainCall | None = None
    previous_teammate_messages: list[Message] = Field(default_factory=list)
    personal_memory: list[str] = Field(default_factory=list)
    shared_memory: list[MemoryEntry] = Field(default_factory=list)
    cs_table: list[CSEntry] = Field(default_factory=list)


def player_role(state: GameState, player_id: str) -> PlayerRole:
    """Determine the Code 1 role for a player (D5: all 6 see REBOUND on loose ball)."""
    if state.ball.status == "LOOSE":
        return "REBOUND"
    player = state.players[player_id]
    if player.team != state.offense:
        return "DEFENSE"
    if player.has_ball:
        return "BALL_HANDLER"
    return "OFF_BALL"


def format_game_clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    mins, secs = divmod(total, 60)
    return f"{mins:02d}:{secs:02d}"


def build_observation(
    state: GameState,
    player_id: str,
    *,
    coordination: CoordinationView | None = None,
    personal_memory: PersonalMemory | list[str] | None = None,
    flags: CoordinationConfig | None = None,
    is_captain: bool = False,
    decision_event_idx: int | None = None,
) -> Observation:
    """Build a structured Observation for ``player_id`` at the upcoming decision event."""
    if player_id not in state.players:
        raise ValueError(f"Unknown player_id: {player_id}")

    coord = coordination or NullCoordinationView()
    cfg_flags = flags or CoordinationConfig()
    me = state.players[player_id]
    team = me.team
    role = player_role(state, player_id)
    # Upcoming decision event is state.event_idx + 1 unless overridden
    target_event_idx = (
        decision_event_idx if decision_event_idx is not None else state.event_idx + 1
    )

    mates = [
        PeerObservation(
            player_id=pid,
            pos=p.pos,
            movement=p.movement,
            speed=p.speed,
            has_ball=p.has_ball,
        )
        for pid, p in sorted(state.players.items())
        if p.team == team and pid != player_id
    ]
    opps = [
        PeerObservation(
            player_id=pid,
            pos=p.pos,
            movement=p.movement,
            speed=p.speed,
            has_ball=p.has_ball,
        )
        for pid, p in sorted(state.players.items())
        if p.team != team
    ]
    matchups = sorted(state.matchups.items())

    game_flags: list[str] = []
    if state.shot_clock_s <= 3.0:
        game_flags.append("SHOT_CLOCK_LOW")
    if state.needs_clear:
        game_flags.append("NEEDS_CLEAR")
    if state.phase == "OT":
        game_flags.append("OVERTIME")

    legal_sorted = sorted(get_legal_actions(state, player_id))
    hints = [format_legal_action_hint(state, player_id, act) for act in legal_sorted]

    # Coordination sections respecting team flags
    cap_call: CaptainCall | None = None
    if cfg_flags.captain:
        cap_call = coord.captain_call(team, target_event_idx)

    raw_inbox = coord.inbox(team, player_id, target_event_idx)
    # Never allow opponent messages into an observation
    team_inbox = [m for m in raw_inbox if m.sender[:1] == team and m.sender != player_id]
    if cfg_flags.comms:
        visible_messages = team_inbox
    elif cfg_flags.captain:
        # Team B (comms=False, captain=True): captain directives still appear
        visible_messages = [
            m for m in team_inbox if m.is_captain_channel and m.kind == "action"
        ]
    else:
        visible_messages = []

    if isinstance(personal_memory, PersonalMemory):
        pm_lines = personal_memory.lines()[-8:]
    elif isinstance(personal_memory, list):
        pm_lines = list(personal_memory)[-8:]
    else:
        pm_lines = []

    shared_mem = coord.shared_memory(team, target_event_idx)
    cs_entries = coord.cs_table(team, target_event_idx)

    return Observation(
        player_id=player_id,
        team=team,
        is_captain=is_captain,
        role=role,
        pos=me.pos,
        has_ball=me.has_ball,
        fatigue=me.fatigue,
        teammates=mates,
        opponents=opps,
        matchups=matchups,
        ball_pos=state.ball.pos,
        ball_status=state.ball.status,
        ball_holder=state.ball.holder,
        offense_team=state.offense,
        event_idx=target_event_idx,
        score=dict(state.score),
        game_clock_s=state.game_clock_s,
        shot_clock_s=state.shot_clock_s,
        team_fouls=dict(state.team_fouls),
        phase=state.phase,
        flags=game_flags,
        legal_actions=legal_sorted,
        legal_action_hints=hints,
        coordination_flags=cfg_flags,
        previous_captain_call=cap_call,
        previous_teammate_messages=visible_messages,
        personal_memory=pm_lines,
        shared_memory=shared_mem,
        cs_table=cs_entries,
    )


def render_observation(obs: Observation) -> str:
    """Render a structured Observation into the exact Code 1 text shown to the LLM."""
    lines: list[str] = []

    # 1. [OWN STATE]
    lines.append("[OWN STATE]")
    lines.append(f"Player: {obs.player_id}")
    lines.append(f"Team: {obs.team}")
    lines.append(f"Role: {obs.role}")
    lines.append(f"Position: ({obs.pos[0]}, {obs.pos[1]})")
    lines.append(f"Has Ball: {'true' if obs.has_ball else 'false'}")
    lines.append(f"Fatigue: {obs.fatigue:.1f}/10")
    lines.append("")

    # 2. [TEAMMATES]
    lines.append("[TEAMMATES]")
    for mate in obs.teammates:
        ball_tag = ", HAS_BALL" if mate.has_ball else ""
        lines.append(
            f"{mate.player_id}: pos=({mate.pos[0]}, {mate.pos[1]}), "
            f"movement={mate.movement}, speed={mate.speed}{ball_tag}"
        )
    lines.append("")

    # 3. [OPPONENTS]
    lines.append("[OPPONENTS]")
    for opp in obs.opponents:
        ball_tag = ", HAS_BALL" if opp.has_ball else ""
        lines.append(
            f"{opp.player_id}: pos=({opp.pos[0]}, {opp.pos[1]}), "
            f"movement={opp.movement}, speed={opp.speed}{ball_tag}"
        )
    lines.append("")

    # 4. [DEFENSIVE MATCHUPS]
    lines.append("[DEFENSIVE MATCHUPS]")
    if obs.matchups:
        for defender, target in obs.matchups:
            lines.append(f"{defender} -> {target}")
    else:
        lines.append("none")
    lines.append("")

    # 5. [BALL]
    lines.append("[BALL]")
    lines.append(f"Position: ({obs.ball_pos[0]}, {obs.ball_pos[1]})")
    lines.append(f"Status: {obs.ball_status}")
    lines.append(f"Holder: {obs.ball_holder if obs.ball_holder else 'none'}")
    lines.append(f"Possession: Team {obs.offense_team}")
    lines.append("")

    # 6. [GAME]
    lines.append("[GAME]")
    lines.append(f"Event: {obs.event_idx}")
    lines.append(
        f"Score: Team A {obs.score.get('A', 0)} - Team B {obs.score.get('B', 0)}"
    )
    lines.append(f"Game Clock: {format_game_clock(obs.game_clock_s)}")
    lines.append(f"Shot Clock: {obs.shot_clock_s:.1f}s")
    lines.append(
        f"Team Fouls: Team A {obs.team_fouls.get('A', 0)}, Team B {obs.team_fouls.get('B', 0)}"
    )
    lines.append(f"Phase: {obs.phase}")
    lines.append(f"Flags: {', '.join(obs.flags) if obs.flags else 'none'}")
    lines.append("")

    # 7. [LEGAL ACTIONS]
    lines.append("[LEGAL ACTIONS]")
    if obs.legal_action_hints:
        for hint in obs.legal_action_hints:
            lines.append(f"- {hint}")
    else:
        lines.append("none")
    lines.append("")

    # 8. [PREVIOUS CAPTAIN CALL]
    lines.append("[PREVIOUS CAPTAIN CALL]")
    if not obs.coordination_flags.captain or obs.previous_captain_call is None:
        lines.append("none")
    else:
        call = obs.previous_captain_call
        call_lines: list[str] = []
        if call.tactic is not None:
            call_lines.append(
                render_message(call.tactic.model_copy(update={"is_captain_channel": True}))
            )
        for d_msg in call.directives:
            call_lines.append(
                render_message(d_msg.model_copy(update={"is_captain_channel": True}))
            )
        if call_lines:
            lines.extend(call_lines)
        else:
            lines.append("none")
    lines.append("")

    # 9. [PREVIOUS TEAMMATE MESSAGES]
    lines.append("[PREVIOUS TEAMMATE MESSAGES]")
    if not obs.previous_teammate_messages:
        lines.append("none")
    else:
        for msg in obs.previous_teammate_messages:
            lines.append(render_message(msg))
    lines.append("")

    # 10. [PERSONAL MEMORY]
    lines.append("[PERSONAL MEMORY]")
    if not obs.personal_memory:
        lines.append("none")
    else:
        for line in obs.personal_memory[-8:]:
            lines.append(line)
    lines.append("")

    # 11. [SHARED TEAM MEMORY]
    lines.append("[SHARED TEAM MEMORY]")
    if not obs.shared_memory:
        lines.append("none")
    else:
        for entry in obs.shared_memory:
            lines.append(
                f"{entry.id}: {entry.opponent} ({entry.category}) — "
                f"{entry.tendency} (confidence: {entry.confidence})"
            )
    lines.append("")

    # 12. [COUNTER-STRATEGY TABLE]
    lines.append("[COUNTER-STRATEGY TABLE]")
    if not obs.cs_table:
        lines.append("empty")
    else:
        for cs in obs.cs_table:
            lines.append(
                f"{cs.key} [{cs.side}]: vs \"{cs.opponent_strategy}\" -> \"{cs.counter_strategy}\""
            )

    return "\n".join(lines)
