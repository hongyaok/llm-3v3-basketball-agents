"""Action legality checks and deterministic invalid-action remapping."""

from bball3x3.engine.court import ZONES
from bball3x3.schemas.actions import (
    ActionProposal,
    RemappedAction,
)
from bball3x3.schemas.state import GameState

BALL_HOLDER_ACTIONS = {
    "SHOOT",
    "PASS",
    "DRIVE",
    "DRIBBLE_MOVE",
    "POST_UP",
    "HOLD",
    "CLEAR",
}

OFF_BALL_ACTIONS = {
    "CUT",
    "CUT_BASELINE",
    "SCREEN",
    "ROLL",
    "POP",
    "SPOT_UP",
    "MOVE",
    "HOLD",
}

DEFENSIVE_ACTIONS = {
    "DEFEND",
    "HELP_PAINT",
    "SWITCH",
    "DOUBLE_TEAM",
    "CONTEST",
    "STEAL_ATTEMPT",
    "DENY",
    "CRASH_BOARDS",
    "BOX_OUT",
    "GET_BACK",
    "MOVE",
    "HOLD",
}

ALL_ACTIONS = (
    BALL_HOLDER_ACTIONS
    | OFF_BALL_ACTIONS
    | DEFENSIVE_ACTIONS
)

TARGET_PLAYER_ACTIONS = {
    "PASS",
    "SCREEN",
    "SWITCH",
    "DOUBLE_TEAM",
    "DENY",
}

REBOUND_ACTIONS = {
    "CRASH_BOARDS",
    "BOX_OUT",
    "GET_BACK",
}

DRIVE_DIRECTIONS: tuple[str, ...] = ("LEFT", "RIGHT", "MIDDLE", "BASELINE")

ZONE_TARGET_ACTIONS = {
    "MOVE",
    "CUT",
    "CUT_BASELINE",
    "SPOT_UP",
    "POP",
    "ROLL",
    "GET_BACK",
    "DRIBBLE_MOVE",
    "POST_UP",
}

OPTIONAL_OPPONENT_TARGET_ACTIONS = {
    "DEFEND",
    "CONTEST",
    "STEAL_ATTEMPT",
}

NO_TARGET_ACTIONS = {
    "SHOOT",
    "HOLD",
    "CLEAR",
    "HELP_PAINT",
    "CRASH_BOARDS",
    "BOX_OUT",
}

# Maps each action to (target_kind, required)
# target_kind in {"teammate", "opponent", "player", "zone", "direction", "none"}
TARGET_SPEC: dict[str, tuple[str, bool]] = {
    "PASS": ("teammate", True),
    "SWITCH": ("teammate", True),
    "SCREEN": ("player", True),
    "DOUBLE_TEAM": ("opponent", True),
    "DENY": ("opponent", True),
    "DEFEND": ("opponent", False),
    "CONTEST": ("opponent", False),
    "STEAL_ATTEMPT": ("opponent", False),
    "MOVE": ("zone", False),
    "CUT": ("zone", False),
    "CUT_BASELINE": ("zone", False),
    "SPOT_UP": ("zone", False),
    "POP": ("zone", False),
    "ROLL": ("zone", False),
    "GET_BACK": ("zone", False),
    "DRIBBLE_MOVE": ("zone", False),
    "POST_UP": ("zone", False),
    "DRIVE": ("direction", False),
    "SHOOT": ("none", False),
    "HOLD": ("none", False),
    "CLEAR": ("none", False),
    "HELP_PAINT": ("none", False),
    "CRASH_BOARDS": ("none", False),
    "BOX_OUT": ("none", False),
}


def _role(state: GameState, player_id: str) -> str:
    """Classify a player for spec fallback selection."""
    if state.ball.status == "LOOSE":
        return "rebound"
    player = state.players[player_id]
    if player.team != state.offense:
        return "defense"
    if player.has_ball:
        return "ball_handler"
    return "offense_offball"


def get_legal_actions(
    state: GameState,
    player_id: str,
) -> set[str]:
    """Return actions permitted for a player in the current state."""

    if player_id not in state.players:
        raise ValueError(f"Unknown player: {player_id}")

    if state.phase not in ("LIVE", "OT"):
        return set()

    # Rebound phase: loose ball after a miss. Everyone crashes, boxes or resets.
    if state.ball.status == "LOOSE":
        return {"CRASH_BOARDS", "BOX_OUT", "GET_BACK", "MOVE", "HOLD"}

    player = state.players[player_id]

    if player.team != state.offense:
        return DEFENSIVE_ACTIONS.copy()

    if player.has_ball:
        actions = BALL_HOLDER_ACTIONS.copy()

        # A newly acquired ball must be cleared beyond the arc.
        if state.needs_clear:
            actions.discard("SHOOT")
        else:
            actions.discard("CLEAR")

        return actions

    return OFF_BALL_ACTIONS.copy()


def format_legal_action_hint(state: GameState, player_id: str, action: str) -> str:
    """Format a legal action with its target hint for the WS3 observation."""
    act = action.upper()
    kind, required = TARGET_SPEC.get(act, ("none", False))
    if kind == "none":
        return act
    actor = state.players[player_id]
    teammates = sorted(
        pid for pid, p in state.players.items() if p.team == actor.team and pid != player_id
    )
    opponents = sorted(
        pid for pid, p in state.players.items() if p.team != actor.team
    )
    if kind == "teammate":
        opts = " | ".join(teammates)
        return f"{act} (target: {opts})"
    if kind == "opponent":
        opts = " | ".join(opponents)
        label = "target" if required else "optional target"
        return f"{act} ({label}: {opts})"
    if kind == "player":
        opts = " | ".join(teammates + opponents)
        return f"{act} (target: {opts})"
    if kind == "zone":
        label = "target" if required else "optional target"
        return f"{act} ({label}: zone)"
    if kind == "direction":
        opts = " | ".join(DRIVE_DIRECTIONS)
        label = "target" if required else "optional target"
        return f"{act} ({label}: {opts})"
    return act


def validate_action(
    state: GameState,
    proposal: ActionProposal,
) -> tuple[bool, str | None, str]:
    """Validate a proposed action.

    Returns (is_valid, invalid_reason, details).
    """

    if proposal.player_id not in state.players:
        return (
            False,
            "BAD_TARGET",
            f"Unknown player: {proposal.player_id}",
        )

    action = proposal.action.upper()

    if action == "__PARSE_FAIL__":
        return (
            False,
            "PARSE_FAIL",
            "LLM output failed structured parsing after repair attempts.",
        )

    if action not in ALL_ACTIONS:
        return (
            False,
            "UNKNOWN_ACTION",
            f"Unknown action: {proposal.action}",
        )

    legal_actions = get_legal_actions(
        state, proposal.player_id
    )

    if action == "CLEAR" and not state.needs_clear:
        return (
            False,
            "INFEASIBLE",
            "CLEAR is only needed after a possession change.",
        )

    if action not in legal_actions:
        return (
            False,
            "ILLEGAL_POSSESSION",
            f"{action} is not legal for {proposal.player_id}",
        )

    kind, required = TARGET_SPEC.get(action, ("none", False))
    raw_target = proposal.target.strip() if proposal.target else None
    if raw_target and raw_target.upper() in ("NONE", "NULL"):
        raw_target = None

    if kind == "none":
        if raw_target is not None:
            return True, None, f"WARN: target {raw_target!r} ignored for {action}"
        return True, None, ""

    if raw_target is None:
        if required:
            return (
                False,
                "BAD_TARGET",
                f"{action} requires a target.",
            )
        return True, None, ""

    target_upper = raw_target.upper()

    if kind in ("teammate", "opponent", "player"):
        if target_upper not in state.players:
            return (
                False,
                "BAD_TARGET",
                f"Unknown target player: {proposal.target}",
            )

        if target_upper == proposal.player_id:
            return (
                False,
                "BAD_TARGET",
                "A player cannot target themselves.",
            )

        actor = state.players[proposal.player_id]
        target = state.players[target_upper]

        if kind == "teammate" and target.team != actor.team:
            return (
                False,
                "BAD_TARGET",
                f"{action} requires a teammate target.",
            )

        if kind == "opponent" and target.team == actor.team:
            return (
                False,
                "BAD_TARGET",
                f"{action} requires an opponent target.",
            )

        return True, None, ""

    if kind == "zone":
        if target_upper not in ZONES:
            return (
                False,
                "BAD_TARGET",
                f"Unknown court zone for {action}: {proposal.target}",
            )
        return True, None, ""

    if kind == "direction":
        if target_upper not in DRIVE_DIRECTIONS:
            return (
                False,
                "BAD_TARGET",
                f"Invalid direction for {action}: {proposal.target}",
            )
        return True, None, ""

    return True, None, ""


def remap_invalid_action(
    state: GameState,
    proposal: ActionProposal,
) -> tuple[ActionProposal, RemappedAction | None]:
    """Replace an illegal action with a safe legal fallback (spec section 3).

    Fallbacks: ball handler -> HOLD, or a safe PASS if the shot clock is
    <= 2; off-ball offense -> SPOT_UP at the nearest open zone (action-only
    here); defender -> DEFEND their assigned matchup; rebound phase ->
    BOX_OUT. Each remap is logged with its invalid reason.
    """

    is_valid, reason, details = validate_action(
        state, proposal
    )

    if is_valid:
        act_upper = proposal.action.upper()
        kind, _ = TARGET_SPEC.get(act_upper, ("none", False))
        raw_t = proposal.target.strip() if proposal.target else None
        if raw_t and raw_t.upper() in ("NONE", "NULL"):
            raw_t = None
        norm_target = None if kind == "none" else (raw_t.upper() if raw_t else None)
        normalized = proposal.model_copy(
            update={"action": act_upper, "target": norm_target}
        )
        return normalized, None

    if proposal.player_id not in state.players:
        raise ValueError(
            f"Cannot remap action for unknown player: "
            f"{proposal.player_id}"
        )

    legal_actions = get_legal_actions(
        state, proposal.player_id
    )

    if not legal_actions:
        raise ValueError(
            "Cannot remap actions while the game is not live."
        )

    role = _role(state, proposal.player_id)
    player = state.players[proposal.player_id]

    if role == "ball_handler" and state.shot_clock_s <= 2.0:
        mate = next(
            (
                pid
                for pid, p in state.players.items()
                if p.team == player.team and pid != proposal.player_id
            ),
            None,
        )
        if mate is not None and "PASS" in legal_actions:
            fallback, fallback_target = "PASS", mate
            details = f"{details} Safe pass under shot-clock pressure.".strip()
            remapped = ActionProposal(
                player_id=proposal.player_id,
                action=fallback,
                target=fallback_target,
                memory_ref=proposal.memory_ref,
            )
            record = RemappedAction(
                player_id=proposal.player_id,
                original_action=proposal.action,
                remapped_action=fallback,
                reason=reason,
                details=details,
            )
            return remapped, record

    if role == "offense_offball" and "SPOT_UP" in legal_actions:
        fallback = "SPOT_UP"
    elif role == "defense" and "DEFEND" in legal_actions:
        fallback = "DEFEND"
    elif role == "rebound" and "BOX_OUT" in legal_actions:
        fallback = "BOX_OUT"
    else:
        fallback = "HOLD"

    if fallback not in legal_actions:
        fallback = "HOLD"
    if fallback not in legal_actions:
        raise ValueError("No safe fallback action available.")

    remapped = ActionProposal(
        player_id=proposal.player_id,
        action=fallback,
        target=None,
        memory_ref=proposal.memory_ref,
    )

    record = RemappedAction(
        player_id=proposal.player_id,
        original_action=proposal.action,
        remapped_action=fallback,
        reason=reason,
        details=details,
    )

    return remapped, record
