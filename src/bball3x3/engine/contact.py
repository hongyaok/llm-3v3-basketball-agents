"""Contact detection (WS1 spec section 4, step 5).

The detector only *annotates* the state. The referee (WS5) judges every
resolved state; this module never decides fouls.
"""

from collections.abc import Mapping

from bball3x3.config import SimulationConfig
from bball3x3.engine.court import Court
from bball3x3.engine.rng import GameRNG
from bball3x3.schemas.referee import ContactEvent, RefereeState
from bball3x3.schemas.state import GameState

DEFAULT_CONTACT = {
    "drive_contest_prob": 0.25,
    "screen_prob": 0.15,
    "rebound_prob": 0.10,
    "reach_prob": 0.2,
}


def contact_params(config: SimulationConfig) -> dict:
    return {**DEFAULT_CONTACT, **config.contact}


def _midpoint(
    a: tuple[int, int], b: tuple[int, int]
) -> tuple[int, int]:
    return ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)


def detect_contact(
    *,
    state: GameState,
    actions: dict[str, str],
    ball_handler_id: str | None,
    primary_defender_id: str | None,
    action_targets: dict[str, str | None] | None = None,
    rebound_phase: bool = False,
    rng: GameRNG,
    config: SimulationConfig,
) -> tuple[ContactEvent, dict]:
    """Annotate contact only when the relevant opposing players are identifiable."""
    params = contact_params(config)
    draws: dict[str, float] = {}
    court = Court(config.court)
    action_targets = action_targets or {}

    upper = {pid: act.upper() for pid, act in actions.items()}
    candidates: list[tuple[str, str, str, float]] = []

    if ball_handler_id and primary_defender_id:
        handler_act = upper.get(ball_handler_id, "HOLD")
        defender_act = upper.get(primary_defender_id, "DEFEND")
        if handler_act == "DRIVE" and defender_act in (
            "DEFEND",
            "CONTEST",
            "DOUBLE_TEAM",
        ):
            draw = rng.random("contact")
            draws["drive_contest"] = draw
            if draw < float(params["drive_contest_prob"]):
                candidates.append(
                    (ball_handler_id, primary_defender_id, "BODY_CONTACT_DRIVE", draw)
                )
        if defender_act == "STEAL_ATTEMPT":
            draw = rng.random("contact")
            draws["reach"] = draw
            if draw < float(params["reach_prob"]):
                candidates.append(
                    (primary_defender_id, ball_handler_id, "REACH", draw)
                )

    for pid, act in upper.items():
        if act != "SCREEN" or pid not in state.players:
            continue
        target = action_targets.get(pid)
        if target is None and ball_handler_id in state.players:
            target = ball_handler_id
        if target not in state.players or state.players[target].team != state.players[pid].team:
            continue
        defender = state.matchups.get(target)
        if (defender not in state.players
                or state.players[defender].team == state.players[pid].team
                or court.distance(state.players[pid].pos, state.players[defender].pos)
                > 2 * court.cell_m):
            continue
        draw = rng.random("contact")
        draws[f"screen_{pid}"] = draw
        if draw < float(params["screen_prob"]):
            candidates.append((pid, defender, "SCREEN_CONTACT", draw))
            break

    if rebound_phase:
        # A box-out against a nearby crasher identifies the contact initiator
        # and recipient. Whether that contact is illegal remains the referee's call.
        pairs = [
            (court.distance(state.players[boxer].pos, state.players[crasher].pos),
             boxer, crasher)
            for boxer, boxer_action in upper.items()
            for crasher, crasher_action in upper.items()
            if boxer_action == "BOX_OUT" and crasher_action == "CRASH_BOARDS"
            and boxer in state.players and crasher in state.players
            and state.players[boxer].team != state.players[crasher].team
            and court.distance(state.players[boxer].pos, state.players[crasher].pos)
            <= 2 * court.cell_m
            and court.distance(state.players[boxer].pos, state.ball.pos)
            <= 3 * court.cell_m
            and court.distance(state.players[crasher].pos, state.ball.pos)
            <= 3 * court.cell_m
        ]
        draw = rng.random("contact")
        draws["rebound"] = draw
        if pairs and draw < float(params["rebound_prob"]):
            _, boxer, crasher = min(pairs)
            candidates.append((boxer, crasher, "LOOSE_BALL", draw))

    if not candidates:
        return ContactEvent(contact_detected=False), draws

    first_off, first_def, contact_type, _ = candidates[0]
    involved = [first_off, first_def]
    loc = _midpoint(state.players[first_off].pos, state.players[first_def].pos)
    details: dict = {"trigger_actions": upper}

    def _moved(pid: str) -> bool:
        player = state.players[pid]
        return player.prev_pos is not None and player.prev_pos != player.pos

    if contact_type == "SCREEN_CONTACT":
        details["screen_target"] = action_targets.get(first_off) or ball_handler_id
        details["contact_recipient"] = first_def
        # Art. 33.7: a screen is legal only if the screener was stationary at contact.
        details["contact_initiator"] = first_off
        details["screener_moving"] = _moved(first_off)
    elif contact_type == "BODY_CONTACT_DRIVE":
        # Art. 33.3/33.8/33.9: a set defender (legal guarding position) is charged into;
        # a defender still moving into the driver's path is responsible for the contact.
        defender_set = not _moved(first_def)
        details["defender_set"] = defender_set
        details["contact_initiator"] = first_off if defender_set else first_def
        details["contact_recipient"] = first_def if defender_set else first_off
    elif contact_type == "LOOSE_BALL":
        details["contact_initiator"] = first_off
        details["contact_recipient"] = first_def
    return (
        ContactEvent(
            contact_detected=True,
            players_involved=involved,
            contact_location=loc,
            contact_type=contact_type,
            details=details,
        ),
        draws,
    )


def build_referee_state(
    *,
    state: GameState,
    contact: ContactEvent,
    current_event: dict,
) -> RefereeState:
    """Assemble the Code 3 referee state for one resolved event."""
    holder: str | None = None
    for pid, player in state.players.items():
        if player.has_ball:
            holder = pid
            break
    return RefereeState(
        event_idx=state.event_idx,
        game_clock_s=state.game_clock_s,
        shot_clock_s=state.shot_clock_s,
        score=dict(state.score),
        team_fouls=dict(state.team_fouls),
        possession=state.offense,
        ball_handler=holder,
        players={pid: p.model_copy(deep=True) for pid, p in state.players.items()},
        matchups=dict(state.matchups),
        ball=state.ball.model_copy(deep=True),
        current_event=current_event,
        contact_event=contact,
    )


def _query_atom(value: object) -> str:
    """Render only scalar evidence, never a dict's insertion-order-dependent repr."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return " ".join(str(value).split()) or "none"
    return "none"


def _query_pos(pos: tuple[int, int] | None) -> str:
    return f"({pos[0]},{pos[1]})" if pos is not None else "none"


def referee_query_text(ref_state: RefereeState) -> str:
    """One stable retrieval/logging query for every resolved state, including no contact."""
    event = ref_state.current_event
    contact = ref_state.contact_event
    raw_actions = event.get("actions")
    if not isinstance(raw_actions, Mapping):
        raw_actions = contact.details.get("trigger_actions")
    actions = (
        {pid: action for pid, action in raw_actions.items()
         if isinstance(pid, str) and isinstance(action, str)}
        if isinstance(raw_actions, Mapping) else {}
    )

    def describe(pid: str | None) -> str:
        if pid is None or pid not in ref_state.players:
            return "none"
        player = ref_state.players[pid]
        return (
            f"{pid}(team={player.team},action={_query_atom(actions.get(pid))},"
            f"move={_query_atom(player.movement)},speed={_query_atom(player.speed)},"
            f"has_ball={_query_atom(player.has_ball)},"
            f"prev={_query_pos(player.prev_pos)},pos={_query_pos(player.pos)})"
        )

    involved = [pid for pid in contact.players_involved if isinstance(pid, str)]
    candidates = involved if contact.contact_detected else []
    if not candidates:
        if ref_state.ball_handler in ref_state.players:
            candidates = [ref_state.ball_handler]
        else:
            event_type = event.get("event_type")
            candidates = sorted(
                pid for pid, action in actions.items()
                if action == event_type and pid in ref_state.players
            )[:1]
        if candidates:
            candidates += sorted(
                pid for pid, target in ref_state.matchups.items()
                if target == candidates[0] and pid in ref_state.players
            )[:1]
    # Label off/def by the team that had the ball when the actions were chosen. The state
    # is post-resolution, so after a made shot, steal or rebound ref_state.possession is
    # already the other team and would swap the roles.
    before = event.get("possession_before")
    role_team = before if before in ("A", "B") else ref_state.possession
    offense = next(
        (pid for pid in candidates if pid in ref_state.players
         and ref_state.players[pid].team == role_team), None,
    )
    defense = next(
        (pid for pid in candidates if pid in ref_state.players
         and ref_state.players[pid].team != role_team), None,
    )
    ordered_actions = ",".join(
        f"{pid}:{_query_atom(actions[pid])}" for pid in sorted(actions)
    ) or "none"
    shot_action = event.get("was_shooting") is True or "SHOOT" in actions.values()
    details = contact.details if contact.contact_detected else {}
    location = contact.contact_location if contact.contact_detected else None
    initiator = details.get("contact_initiator", details.get("offender"))
    recipient = details.get("contact_recipient", details.get("fouled_player"))
    fields = [
        f"event={_query_atom(event.get('event_type'))}",
        f"contact={_query_atom(contact.contact_detected)}",
        f"contact_type={_query_atom(contact.contact_type) if contact.contact_detected else 'none'}",
        f"involved={','.join(involved) if contact.contact_detected and involved else 'none'}",
        f"off={describe(offense)}",
        f"def={describe(defense)}",
        f"contact_location={_query_pos(location)}",
        f"contact_initiator={_query_atom(initiator)}",
        f"contact_recipient={_query_atom(recipient)}",
        f"screen_target={_query_atom(details.get('screen_target'))}",
        f"screener_moving={_query_atom(details.get('screener_moving'))}",
        f"defender_set={_query_atom(details.get('defender_set'))}",
        f"ball={ref_state.ball.status}",
        f"holder={_query_atom(ref_state.ball_handler)}",
        f"possession={ref_state.possession}",
        f"possession_before={role_team}",
        f"shot_in_air={_query_atom(ref_state.ball.status == 'IN_SHOT')}",
        f"shooting_action={_query_atom(shot_action)}",
        f"objective_violation={_query_atom(event.get('objective_violation') is True)}",
        f"offensive_contact={_query_atom(event.get('offensive_contact') is True)}",
        f"technical_conduct={_query_atom(event.get('technical_conduct') is True)}",
        f"unsportsmanlike_contact={_query_atom(event.get('unsportsmanlike_contact') is True)}",
        f"judgement_violation={_query_atom(event.get('judgement_violation'))}",
        f"event_offender={_query_atom(event.get('offender'))}",
        f"event_fouled_player={_query_atom(event.get('fouled_player'))}",
        f"actions={ordered_actions}",
    ]
    conduct = event.get("conduct_evidence")
    if isinstance(conduct, Mapping):
        fields.append(
            f"conduct={_query_atom(conduct.get('kind'))} "
            f"actor={_query_atom(conduct.get('actor'))} "
            f"target={_query_atom(conduct.get('target'))}"
        )
    return "; ".join(fields)


def empty_contact() -> ContactEvent:
    return ContactEvent(contact_detected=False)


def court_from_config(config: SimulationConfig) -> Court:
    return Court(config.court)
