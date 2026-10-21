from typing import Literal

from pydantic import BaseModel

ActionType = Literal[
    "SHOOT",
    "PASS",
    "DRIVE",
    "DRIBBLE_MOVE",
    "POST_UP",
    "HOLD",
    "CUT",
    "CUT_BASELINE",
    "SCREEN",
    "ROLL",
    "POP",
    "SPOT_UP",
    "MOVE",
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
    "CLEAR",
]

InvalidReason = Literal[
    "PARSE_FAIL",
    "UNKNOWN_ACTION",
    "ILLEGAL_POSSESSION",
    "INFEASIBLE",
    "BAD_TARGET",
]

ConductType = Literal["TECHNICAL", "UNSPORTSMANLIKE"]

class ActionProposal(BaseModel):
    player_id: str
    action: str
    target: str | None = None
    memory_ref: list[str] | None = None
    # Explicit simulation evidence. An unsportsmanlike signal must name the
    # opposing player contacted; the engine verifies the resolved contact.
    conduct: ConductType | None = None
    conduct_target: str | None = None

class RemappedAction(BaseModel):
    player_id: str
    original_action: str
    remapped_action: str
    reason: InvalidReason
    details: str = ""
