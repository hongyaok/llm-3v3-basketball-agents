"""Coordination-flag filtering for parsed AgentOutputs (WS3 §3.5)."""

from __future__ import annotations

from bball3x3.schemas.agent import AgentOutput, CoordinationConfig
from bball3x3.schemas.memory import CSProposal, MemoryProposal
from bball3x3.schemas.messages import CaptainCall, Message


class SuppressedItems(list[Message]):
    """A list of suppressed Messages that also records suppressed call/memory/CS proposals."""

    def __init__(
        self,
        messages: list[Message] | None = None,
        *,
        captain_call: CaptainCall | None = None,
        memory_update: MemoryProposal | None = None,
        cs_update: CSProposal | None = None,
    ) -> None:
        super().__init__(messages or [])
        self.captain_call = captain_call
        self.memory_update = memory_update
        self.cs_update = cs_update


def apply_flags(
    output: AgentOutput,
    flags: CoordinationConfig,
    is_captain: bool,
) -> tuple[AgentOutput, SuppressedItems]:
    """Filter an AgentOutput according to the team's coordination flags.

    Rules (WS3_PLAN §3.5 & IMPLEMENTATION_PLAN §WS3):
    - Comms off (`flags.comms == False`): non-captains' `MESSAGES` are dropped,
      and so are the captain's ordinary messages. `CAPTAIN_CALL` is kept (for
      the captain when `flags.captain == True`).
    - Captain off (`flags.captain == False`) or `not is_captain`: `CAPTAIN_CALL`
      is dropped. When `flags.captain == False`, `[tactic]` lines in `MESSAGES`
      stay ordinary messages (`is_captain_channel=False`).
    - Memory write off (`flags.memory_write == False`): `MEMORY_UPDATE` and
      `CS_UPDATE` are dropped.
    - All dropped items are returned in `SuppressedItems` for `suppressed=True` logging.
    """
    kept_messages: list[Message] = []
    suppressed_messages: list[Message] = []

    for msg in output.messages:
        # Normalize accidental captain marker from non-captain or when captain flag is off
        normalized = msg
        if not is_captain or not flags.captain:
            if msg.is_captain_channel:
                normalized = msg.model_copy(update={"is_captain_channel": False})

        if not flags.comms:
            # Comms off: ordinary teammate messages (including from captain) are dropped.
            suppressed_messages.append(normalized)
        else:
            kept_messages.append(normalized)

    kept_captain_call: CaptainCall | None = output.captain_call
    suppressed_captain_call: CaptainCall | None = None

    if output.captain_call is not None:
        if not is_captain or not flags.captain:
            kept_captain_call = None
            suppressed_captain_call = output.captain_call
            if output.captain_call.tactic is not None:
                suppressed_messages.append(
                    output.captain_call.tactic.model_copy(update={"is_captain_channel": True})
                )
            for d_msg in output.captain_call.directives:
                suppressed_messages.append(
                    d_msg.model_copy(update={"is_captain_channel": True})
                )

    kept_memory_update: MemoryProposal | None = output.memory_update
    suppressed_memory_update: MemoryProposal | None = None
    kept_cs_update: CSProposal | None = output.cs_update
    suppressed_cs_update: CSProposal | None = None

    if not flags.memory_write:
        if output.memory_update is not None:
            kept_memory_update = None
            suppressed_memory_update = output.memory_update
        if output.cs_update is not None:
            kept_cs_update = None
            suppressed_cs_update = output.cs_update

    kept = output.model_copy(
        update={
            "messages": kept_messages,
            "captain_call": kept_captain_call,
            "memory_update": kept_memory_update,
            "cs_update": kept_cs_update,
        }
    )
    suppressed = SuppressedItems(
        suppressed_messages,
        captain_call=suppressed_captain_call,
        memory_update=suppressed_memory_update,
        cs_update=suppressed_cs_update,
    )
    return kept, suppressed
