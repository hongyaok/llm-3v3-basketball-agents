from collections.abc import Callable
from typing import Any

from .base import CallParams, LLMResponse, Messages


# scripted stand-in for the real client, so tests and ci need no api key
class FakeLLM:
    def __init__(self, replies: list[str] | Callable[[Messages], str]):
        self._replies = replies if callable(replies) else list(replies)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: Messages,
        params: CallParams,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {"messages": messages, "model": params.model, "response_format": response_format}
        )
        if callable(self._replies):
            text = self._replies(messages)
        elif self._replies:
            text = self._replies.pop(0)
        else:
            raise RuntimeError("FakeLLM has no scripted reply left")
        return LLMResponse(text=text, model=params.model)
