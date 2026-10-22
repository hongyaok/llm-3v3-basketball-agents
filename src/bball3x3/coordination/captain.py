"""Persistent captain calls with next-event visibility."""

from bball3x3.schemas.messages import CaptainCall


class CaptainStore:
    """Store one team's captain calls for a single game."""

    def __init__(self) -> None:
        self._calls: list[tuple[int, CaptainCall]] = []
        self._latest_event = 0

    def post(self, event_idx: int, call: CaptainCall) -> None:
        """Apply a captain submission, effective from event_idx + 1."""
        if event_idx < 1:
            raise ValueError("Event index must be positive")
        if event_idx <= self._latest_event:
            raise ValueError("Captain submissions must use increasing events")

        self._latest_event = event_idx

        if call.maintain:
            return

        # An empty submission does not clear the existing call.
        if call.tactic is None and not call.directives:
            return

        stored = call.model_copy(deep=True)
        messages = list(stored.directives)
        if stored.tactic is not None:
            messages.append(stored.tactic)

        for message in messages:
            message.is_captain_channel = True
            message.text = message.text[:200]

        self._calls.append((event_idx, stored))

    def current(self, event_idx: int) -> CaptainCall | None:
        """Return the most recent call visible at this decision event."""
        for written_at, call in reversed(self._calls):
            if written_at < event_idx:
                return call.model_copy(deep=True)

        return None