
"""Action legality checks and deterministic invalid-action remapping."""

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


def get_legal_actions(
    state: GameState,
    player_id: str,
) -> set[str]:
    """Return actions permitted for a player in the current state."""

    if player_id not in state.players:
        raise ValueError(f"Unknown player: {player_id}")

    if state.phase not in ("LIVE", "OT"):
        return set()

    player = state.players[player_id]

    if player.team != state.offense:
        return DEFENSIVE_ACTIONS.copy()

    if player.has_ball:
        actions = BALL_HOLDER_ACTIONS.copy()

        # A newly acquired ball must be cleared beyond the arc.
        if state.needs_clear:
            actions.discard("SHOOT")

        return actions

    return OFF_BALL_ACTIONS.copy()


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

    if action not in ALL_ACTIONS:
        return (
            False,
            "UNKNOWN_ACTION",
            f"Unknown action: {proposal.action}",
        )

    legal_actions = get_legal_actions(
        state, proposal.player_id
    )

    if action not in legal_actions:
        return (
            False,
            "ILLEGAL_POSSESSION",
            f"{action} is not legal for {proposal.player_id}",
        )

    if action == "CLEAR" and not state.needs_clear:
        return (
            False,
            "INFEASIBLE",
            "CLEAR is only needed after a possession change.",
        )

    if action in TARGET_PLAYER_ACTIONS:
        if not proposal.target:
            return (
                False,
                "BAD_TARGET",
                f"{action} requires a target player.",
            )

        if proposal.target not in state.players:
            return (
                False,
                "BAD_TARGET",
                f"Unknown target player: {proposal.target}",
            )

        actor = state.players[proposal.player_id]
        target = state.players[proposal.target]

        if action in {"PASS", "SCREEN"}:
            if target.team != actor.team:
                return (
                    False,
                    "BAD_TARGET",
                    f"{action} requires a teammate target.",
                )

        if action in {"DOUBLE_TEAM", "DENY"}:
            if target.team == actor.team:
                return (
                    False,
                    "BAD_TARGET",
                    f"{action} requires an opponent target.",
                )

        if proposal.target == proposal.player_id:
            return (
                False,
                "BAD_TARGET",
                "A player cannot target themselves.",
            )

    return True, None, ""


def remap_invalid_action(
    state: GameState,
    proposal: ActionProposal,
) -> tuple[ActionProposal, RemappedAction | None]:
    """Replace an illegal action with a safe legal fallback."""

    is_valid, reason, details = validate_action(
        state, proposal
    )

    if is_valid:
        normalized = proposal.model_copy(
            update={"action": proposal.action.upper()}
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

    # HOLD is available to all player roles.
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
