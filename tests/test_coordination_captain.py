"""Tests for WS4 captain-call persistence and visibility."""

import pytest

from bball3x3.coordination.captain import CaptainStore
from bball3x3.schemas.messages import CaptainCall, Message


def tactic_call(text: str) -> CaptainCall:
    return CaptainCall(
        tactic=Message(sender="A1", kind="tactic", text=text)
    )


def test_call_visible_only_from_next_event():
    store = CaptainStore()
    store.post(1, tactic_call("Spread out"))

    assert store.current(1) is None
    assert store.current(2).tactic.text == "Spread out"


def test_maintain_preserves_previous_call():
    store = CaptainStore()
    store.post(1, tactic_call("Spread out"))
    store.post(2, CaptainCall(maintain=True))

    assert store.current(3).tactic.text == "Spread out"
    assert store.current(10).tactic.text == "Spread out"


def test_maintain_without_previous_call_stays_empty():
    store = CaptainStore()
    store.post(1, CaptainCall(maintain=True))

    assert store.current(2) is None


def test_replacement_preserves_historical_visibility():
    store = CaptainStore()
    store.post(1, tactic_call("Spread out"))
    store.post(3, tactic_call("Attack the paint"))

    assert store.current(3).tactic.text == "Spread out"
    assert store.current(4).tactic.text == "Attack the paint"
    assert store.current(2).tactic.text == "Spread out"


def test_empty_submission_preserves_call():
    store = CaptainStore()
    store.post(1, tactic_call("Spread out"))
    store.post(2, CaptainCall())

    assert store.current(3).tactic.text == "Spread out"


def test_copies_and_message_limits():
    store = CaptainStore()
    original = tactic_call("x" * 250)
    store.post(1, original)

    original.tactic.text = "Changed after posting"
    visible = store.current(2)

    assert visible.tactic.text == "x" * 200
    assert visible.tactic.is_captain_channel is True

    visible.tactic.text = "Changed after reading"
    assert store.current(2).tactic.text == "x" * 200


def test_directive_only_call():
    store = CaptainStore()
    store.post(1, CaptainCall(directives=[
        Message(sender="A1", kind="action", text="Set a screen")
    ]))

    visible = store.current(2)
    assert visible.tactic is None
    assert visible.directives[0].text == "Set a screen"
    assert visible.directives[0].is_captain_channel is True


def test_reject_duplicate_or_past_submission():
    store = CaptainStore()
    store.post(2, CaptainCall(maintain=True))

    for event_idx in (1, 2):
        with pytest.raises(ValueError, match="increasing events"):
            store.post(event_idx, tactic_call("Spread out"))