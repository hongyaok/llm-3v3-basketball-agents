"""CS visibility, reference counting, rejection, and ablation."""

from bball3x3.agents.context import SimpleCoordinationView
from bball3x3.schemas.agent import AgentOutput, CoordinationConfig
from bball3x3.schemas.memory import CSProposal
from bball3x3.schemas.messages import CaptainCall, Message


def cs_proposal(counter="Move the ball"):
    return CSProposal(
        opponent_strategy="Zone defense",
        counter_strategy=counter,
        side="offense",
    )


def submit(view, event_idx, outputs, flags=None):
    return view.record_event(
        event_idx,
        outputs,
        {"A": flags if flags is not None else CoordinationConfig()},
    )


def test_cs_write_and_merge_preserve_event_visibility():
    view = SimpleCoordinationView()
    submit(view, 1, {
        "A1": AgentOutput(action="HOLD", cs_update=cs_proposal())
    })
    _, writes = submit(view, 2, {
        "A1": AgentOutput(
            action="HOLD",
            cs_update=cs_proposal("Attack the gaps"),
        )
    })

    assert view.cs_table("A", 1) == []
    assert view.cs_table("A", 2)[0].counter_strategy == "Move the ball"
    assert view.cs_table("A", 3)[0].counter_strategy == "Attack the gaps"
    assert writes[0]["merged"]
    assert writes[0]["key"] == "01"
    assert view.cs_table("B", 3) == []


def test_same_event_reference_is_not_counted():
    view = SimpleCoordinationView()
    submit(view, 1, {
        "A1": AgentOutput(action="HOLD", cs_update=cs_proposal()),
        "A2": AgentOutput(
            action="HOLD",
            messages=[
                Message(
                    sender="A2", kind="tactic", text="Use the counter", cs="01"
                )
            ],
        ),
    })

    assert view.cs_table("A", 2)[0].times_referenced == 0

    submit(view, 2, {
        "A2": AgentOutput(
            action="HOLD",
            messages=[
                Message(
                    sender="A2", kind="tactic", text="Use the counter", cs="01"
                ),
                Message(
                    sender="A2", kind="tactic", text="Unknown counter", cs="99"
                ),
            ],
        )
    })

    assert view.cs_table("A", 2)[0].times_referenced == 0
    assert view.cs_table("A", 3)[0].times_referenced == 1


def test_captain_reference_counts_with_comms_off():
    view = SimpleCoordinationView()
    submit(view, 1, {
        "A1": AgentOutput(action="HOLD", cs_update=cs_proposal())
    })
    submit(view, 2, {
        "A1": AgentOutput(
            action="HOLD",
            captain_call=CaptainCall(
                tactic=Message(
                    sender="A1", kind="tactic", text="Move the ball", cs="01"
                )
            ),
        )
    }, flags=CoordinationConfig(comms=False))

    submit(view, 3, {
        "A1": AgentOutput(
            action="HOLD",
            captain_call=CaptainCall(maintain=True),
        )
    }, flags=CoordinationConfig(comms=False))

    assert view.cs_table("A", 4)[0].times_referenced == 1


def test_memory_write_off_keeps_cs_empty():
    view = SimpleCoordinationView()
    _, writes = submit(view, 1, {
        "A1": AgentOutput(action="HOLD", cs_update=cs_proposal())
    }, flags=CoordinationConfig(memory_write=False))

    assert writes == []
    assert view.cs_table("A", 2) == []


def test_invalid_proposal_is_logged_as_rejected():
    view = SimpleCoordinationView()
    _, writes = submit(view, 1, {
        "A1": AgentOutput(action="HOLD", cs_update=cs_proposal("   "))
    })

    assert not writes[0]["accepted"]
    assert view.cs_table("A", 2) == []