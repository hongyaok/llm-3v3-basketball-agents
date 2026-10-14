from typing import Any, Protocol

from pydantic import BaseModel

from ..config import LLMPlayersConfig, LLMRefereeConfig

Messages = list[dict[str, str]]
CallParams = LLMPlayersConfig | LLMRefereeConfig

# one completed llm call, with the accounting the event log needs
class LLMResponse(BaseModel):
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    cached: bool = False
    attempts: int = 1

# anything that can answer a chat request: the real client or FakeLLM
class LLMBackend(Protocol):
    async def complete(
        self,
        messages: Messages,
        params: CallParams,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse: ...
