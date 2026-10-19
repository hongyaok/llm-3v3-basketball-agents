from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from .base import CallParams, LLMBackend, LLMResponse, Messages

T = TypeVar("T")

# parser contract: return (parsed value, list of errors); no errors means valid
Parser = Callable[[str], tuple[T, list[str]]]

REPAIR_PROMPT = (
    "Your previous reply could not be used because of these errors:\n{errors}\n"
    "Reply again with only the corrected structured output."
)


@dataclass
class RepairResult(Generic[T]):
    parsed: T
    ok: bool
    errors: list[str]
    responses: list[LLMResponse] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.responses)


# call the llm, and on parse errors re-ask with the errors up to repair_attempts times
async def complete_with_repair(
    llm: LLMBackend,
    messages: Messages,
    params: CallParams,
    parse: Parser[T],
    response_format: dict[str, Any] | None = None,
) -> RepairResult[T]:
    repair_attempts = getattr(params, "repair_attempts", 0)
    conversation = list(messages)
    responses: list[LLMResponse] = []

    for attempt in range(repair_attempts + 1):
        response = await llm.complete(conversation, params, response_format)
        responses.append(response)
        parsed, errors = parse(response.text)
        if not errors:
            return RepairResult(parsed, True, [], responses)
        if attempt < repair_attempts:
            conversation = conversation + [
                {"role": "assistant", "content": response.text},
                {"role": "user", "content": REPAIR_PROMPT.format(errors="\n".join(errors))},
            ]

    return RepairResult(parsed, False, errors, responses)
