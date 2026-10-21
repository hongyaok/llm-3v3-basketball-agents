"""Contact detection (WS1 spec section 4, step 5).

The detector only *annotates* the state. The referee (WS5) judges every
resolved state; this module never decides fouls.
"""

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
    if contact_type == "SCREEN_CONTACT":
        details["screen_target"] = action_targets.get(first_off) or ball_handler_id
        details["contact_recipient"] = first_def
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


def referee_query_text(ref_state: RefereeState) -> str:
    """Deterministic templated query over event + contact fields (WS5)."""
    event = ref_state.current_event
    contact = ref_state.contact_event
    conduct = event.get("conduct_evidence")
    conduct_text = (
        f"; conduct={conduct['kind']} actor={conduct['actor']}"
        f" target={conduct.get('target', 'none')}"
        if isinstance(conduct, dict) else ""
    )
    return (
        f"{event.get('event_type', 'UNKNOWN')}; "
        f"contact={contact.contact_detected}; "
        f"{contact.contact_type} between "
        f"{','.join(contact.players_involved) or 'none'} "
        f"at {contact.contact_location}; "
        f"ball={ref_state.ball.status} holder={ref_state.ball_handler}; "
        f"possession={ref_state.possession}{conduct_text}"
    )


def empty_contact() -> ContactEvent:
    return ContactEvent(contact_detected=False)


def court_from_config(config: SimulationConfig) -> Court:
    return Court(config.court)
