"""Unit tests for coordination flag filtering (src/bball3x3/agents/filtering.py)."""

from bball3x3.agents.filtering import apply_flags
from bball3x3.schemas.agent import AgentOutput, CoordinationConfig
from bball3x3.schemas.memory import CSProposal, MemoryProposal
from bball3x3.schemas.messages import CaptainCall, Directive, Message


def _sample_full_output() -> AgentOutput:
    return AgentOutput(
        action="PASS",
        target="A2",
        memory_ref=["M01"],
        messages=[
            Message(
                sender="A1",
                is_captain_channel=False,
                kind="action",
                text="cut to the rim",
                directive=Directive(to="A2", act="CUT", target="PAINT"),
            ),
            Message(
                sender="A1",
                is_captain_channel=False,
                kind="tactic",
                text="let's run horns",
                cs="01",
            ),
        ],
        captain_call=CaptainCall(
            maintain=False,
            tactic=Message(
                sender="A1",
                is_captain_channel=True,
                kind="tactic",
                text="pick and roll on left wing",
                cs="01",
            ),
            directives=[
                Message(
                    sender="A1",
                    is_captain_channel=True,
                    kind="action",
                    text="screen for A2",
                    directive=Directive(to="A3", act="SCREEN", target="A2"),
                )
            ],
        ),
        memory_update=MemoryProposal(
            opponent="B1",
            category="defensive_tendency",
            tendency="gambles on steals",
        ),
        cs_update=CSProposal(
            side="offense",
            opponent_strategy="switches screens",
            counter_strategy="slip early",
        ),
        rationale="A2 is open",
    )


def test_team_a_all_flags_on_keeps_everything_for_captain():
    out = _sample_full_output()
    flags = CoordinationConfig(comms=True, captain=True, memory_write=True)
    kept, suppressed = apply_flags(out, flags, is_captain=True)

    assert len(kept.messages) == 2
    assert kept.captain_call is not None
    assert kept.memory_update is not None
    assert kept.cs_update is not None
    assert list(suppressed) == []
    assert suppressed.captain_call is None
    assert suppressed.memory_update is None
    assert suppressed.cs_update is None


def test_team_b_comms_off_suppresses_messages_but_keeps_captain_directives():
    out = _sample_full_output()
    flags = CoordinationConfig(comms=False, captain=True, memory_write=True)

    # Captain: ordinary messages dropped, but CAPTAIN_CALL (tactic + directives) survives!
    kept_cap, sup_cap = apply_flags(out, flags, is_captain=True)
    assert kept_cap.messages == []
    assert kept_cap.captain_call is not None
    assert len(kept_cap.captain_call.directives) == 1
    assert kept_cap.memory_update is not None
    assert kept_cap.cs_update is not None
    assert len(sup_cap) == 2

    # Non-captain: messages dropped and any accidental captain_call also dropped
    kept_non, sup_non = apply_flags(out, flags, is_captain=False)
    assert kept_non.messages == []
    assert kept_non.captain_call is None
    assert kept_non.memory_update is not None
    assert kept_non.cs_update is not None
    assert len(sup_non) == 4  # 2 ordinary + 1 captain tactic + 1 captain directive


def test_team_c_captain_off_drops_captain_call_only():
    out = _sample_full_output()
    flags = CoordinationConfig(comms=True, captain=False, memory_write=True)
    kept, suppressed = apply_flags(out, flags, is_captain=True)

    assert len(kept.messages) == 2
    assert all(not m.is_captain_channel for m in kept.messages)
    assert kept.captain_call is None
    assert kept.memory_update is not None
    assert kept.cs_update is not None
    assert suppressed.captain_call is not None
    assert len(suppressed) == 2  # captain tactic + directive


def test_team_d_memory_write_off_drops_memory_and_cs_updates_only():
    out = _sample_full_output()
    flags = CoordinationConfig(comms=True, captain=True, memory_write=False)
    kept, suppressed = apply_flags(out, flags, is_captain=True)

    assert len(kept.messages) == 2
    assert kept.captain_call is not None
    assert kept.memory_update is None
    assert kept.cs_update is None
    assert list(suppressed) == []
    assert suppressed.memory_update is not None
    assert suppressed.cs_update is not None
