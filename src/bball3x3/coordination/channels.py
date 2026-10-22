"""Team communication with next-event delivery and bounded history."""

from bball3x3.schemas.messages import Message


class CommsChannel:
    """One team's messages, visible for the next two decision events."""

    def __init__(self, team: str) -> None:
        if team not in {"A", "B"}:
            raise ValueError("Team must be A or B")

        self.team = team
        self._messages: dict[int, list[Message]] = {}
        self._latest_event = 0

    def post(self, event_idx: int, messages: list[Message]) -> None:
        """Store messages from event t; they first become visible at t+1."""
        if event_idx < 1:
            raise ValueError("Event index must be positive")
        if event_idx < self._latest_event:
            raise ValueError("Cannot post to a past event")

        self._latest_event = event_idx

        # Retain only the events needed for the upcoming observation.
        self._messages = {
            event: stored
            for event, stored in self._messages.items()
            if event >= event_idx - 1
        }

        stored = self._messages.setdefault(event_idx, [])

        for message in messages:
            if message.sender[:1] != self.team:
                continue

            copied = message.model_copy(deep=True)
            copied.text = copied.text[:200]
            stored.append(copied)

        # Older messages from this event can never enter the newest six.
        self._messages[event_idx] = stored[-6:]

    def deliver(self, event_idx: int, player_id: str) -> list[Message]:
        """Return the newest six teammate messages from t-2 and t-1."""
        if player_id[:1] != self.team:
            return []

        visible = [
            message
            for event in (event_idx - 2, event_idx - 1)
            for message in self._messages.get(event, [])
            if message.sender != player_id
        ]

        return [message.model_copy(deep=True) for message in visible[-6:]]