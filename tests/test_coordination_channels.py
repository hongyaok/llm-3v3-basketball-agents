"""Tests for WS4 team communication."""

import pytest

from bball3x3.coordination.channels import CommsChannel
from bball3x3.schemas.messages import Message


def test_next_event_delivery_and_expiry():
    channel = CommsChannel("A")
    channel.post(1, [Message(sender="A1", text="Screen for me")])

    assert channel.deliver(1, "A2") == []
    assert channel.deliver(2, "A2")[0].text == "Screen for me"
    assert channel.deliver(3, "A2")[0].text == "Screen for me"
    assert channel.deliver(4, "A2") == []


def test_team_isolation_and_no_self_delivery():
    channel = CommsChannel("A")
    channel.post(1, [
        Message(sender="A1", text="Team message"),
        Message(sender="B1", text="Opponent message"),
    ])

    assert channel.deliver(2, "B2") == []
    assert channel.deliver(2, "A1") == []
    assert [m.text for m in channel.deliver(2, "A2")] == ["Team message"]


def test_newest_six_messages_across_two_events():
    channel = CommsChannel("A")
    channel.post(1, [
        Message(sender="A1", text=str(i)) for i in range(4)
    ])
    channel.post(2, [
        Message(sender="A3", text=str(i)) for i in range(4, 8)
    ])

    assert [m.text for m in channel.deliver(3, "A2")] == [
        "2", "3", "4", "5", "6", "7",
    ]


def test_text_limit_and_copy_isolation():
    channel = CommsChannel("A")
    original = Message(sender="A1", text="x" * 250)
    channel.post(1, [original])

    original.text = "Changed after posting"
    delivered = channel.deliver(2, "A2")
    assert delivered[0].text == "x" * 200

    delivered[0].text = "Changed after delivery"
    assert channel.deliver(2, "A2")[0].text == "x" * 200


def test_multiple_posts_in_same_event():
    channel = CommsChannel("A")
    channel.post(1, [Message(sender="A1", text="First")])
    channel.post(1, [Message(sender="A3", text="Second")])

    assert [m.text for m in channel.deliver(2, "A2")] == [
        "First", "Second",
    ]


def test_reject_past_event():
    channel = CommsChannel("A")
    channel.post(2, [])

    with pytest.raises(ValueError, match="past event"):
        channel.post(1, [])