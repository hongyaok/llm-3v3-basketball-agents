"""Integration of WS4 channels with the WS3 coordination view."""

from bball3x3.agents.context import SimpleCoordinationView
from bball3x3.schemas.agent import AgentOutput, CoordinationConfig
from bball3x3.schemas.messages import CaptainCall, Message


def captain_output(sender="A1"):
    return AgentOutput(
        action="HOLD",
        messages=[Message(sender=sender, text="Ordinary message")],
        captain_call=CaptainCall(
            tactic=Message(sender=sender, kind="tactic", text="Spread out"),
            directives=[
                Message(sender=sender, kind="action", text="Set a screen")
            ],
        ),
    )


def test_comms_off_preserves_captain_channel():
    view = SimpleCoordinationView()
    view.record_event(
        1,
        {"A1": captain_output()},
        {"A": CoordinationConfig(comms=False)},
    )

    assert view.captain_call("A", 1) is None
    assert view.inbox("A", "A2", 1) == []
    assert view.captain_call("A", 2).tactic.text == "Spread out"
    assert [m.text for m in view.inbox("A", "A2", 2)] == [
        "Set a screen"
    ]
    assert view.inbox("A", "A2", 2)[0].is_captain_channel
    assert view.inbox("A", "B2", 2) == []


def test_captain_off_preserves_ordinary_messages():
    view = SimpleCoordinationView()
    view.record_event(
        1,
        {"A1": captain_output()},
        {"A": CoordinationConfig(captain=False)},
    )

    assert view.captain_call("A", 2) is None
    assert [m.text for m in view.inbox("A", "A2", 2)] == [
        "Ordinary message"
    ]


def test_only_configured_captain_can_submit_call():
    view = SimpleCoordinationView(captains={"A": "A2", "B": "B2"})
    view.record_event(
        1, {"A1": captain_output("A1")}, {"A": CoordinationConfig()}
    )
    assert view.captain_call("A", 2) is None

    view.record_event(
        2, {"A2": captain_output("A2")}, {"A": CoordinationConfig()}
    )
    assert view.captain_call("A", 3).tactic.sender == "A2"


def test_tactic_suggestion_reaches_captain_without_becoming_call():
    view = SimpleCoordinationView()
    view.record_event(
        1,
        {"A2": AgentOutput(
            action="HOLD",
            messages=[
                Message(sender="A2", kind="tactic", text="Try switching")
            ],
        )},
        {"A": CoordinationConfig()},
    )

    assert view.inbox("A", "A1", 2)[0].text == "Try switching"
    assert view.captain_call("A", 2) is None


def test_spoofed_message_is_not_stored():
    view = SimpleCoordinationView()
    view.record_event(
        1,
        {"A2": AgentOutput(
            action="HOLD",
            messages=[Message(sender="A1", text="Spoofed message")],
        )},
        {"A": CoordinationConfig()},
    )

    assert view.inbox("A", "A3", 2) == []