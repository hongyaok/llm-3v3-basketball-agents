import asyncio

from bball3x3.config import LLMPlayersConfig, LLMRefereeConfig
from bball3x3.llm import FakeLLM
from bball3x3.llm.repair import complete_with_repair

MSGS = [{"role": "user", "content": "you are A1"}]


def parse_upper(text):
    # toy parser: valid iff the reply is all upper case
    return text, ([] if text.isupper() else [f"not upper case: {text!r}"])


def run(coro):
    return asyncio.run(coro)


def test_valid_first_reply_needs_no_repair():
    llm = FakeLLM(["PASS"])
    result = run(complete_with_repair(llm, MSGS, LLMPlayersConfig(), parse_upper))
    assert result.ok is True
    assert result.parsed == "PASS"
    assert result.errors == []
    assert len(result.responses) == 1


def test_invalid_reply_is_reasked_with_errors():
    llm = FakeLLM(["pass", "PASS"])
    result = run(complete_with_repair(llm, MSGS, LLMPlayersConfig(), parse_upper))

    assert result.ok is True
    assert result.parsed == "PASS"
    assert len(result.responses) == 2
    repair_messages = llm.calls[1]["messages"]
    assert repair_messages[: len(MSGS)] == MSGS
    assert repair_messages[len(MSGS)] == {"role": "assistant", "content": "pass"}
    assert repair_messages[-1]["role"] == "user"
    assert "not upper case: 'pass'" in repair_messages[-1]["content"]


def test_gives_up_after_repair_attempts():
    llm = FakeLLM(["pass", "still bad"])
    result = run(
        complete_with_repair(llm, MSGS, LLMPlayersConfig(repair_attempts=1), parse_upper)
    )
    assert result.ok is False
    assert result.parsed == "still bad"
    assert result.errors == ["not upper case: 'still bad'"]
    assert len(llm.calls) == 2


def test_zero_repair_attempts_means_single_call():
    llm = FakeLLM(["pass"])
    result = run(
        complete_with_repair(llm, MSGS, LLMPlayersConfig(repair_attempts=0), parse_upper)
    )
    assert result.ok is False
    assert len(llm.calls) == 1


def test_referee_params_do_not_repair():
    llm = FakeLLM(["bad"])
    result = run(complete_with_repair(llm, MSGS, LLMRefereeConfig(), parse_upper))
    assert result.ok is False
    assert len(llm.calls) == 1


def test_totals_sum_over_all_attempts():
    llm = FakeLLM(["pass", "PASS"])
    result = run(complete_with_repair(llm, MSGS, LLMPlayersConfig(), parse_upper))
    result.responses[0].cost_usd = 0.1
    result.responses[1].cost_usd = 0.2
    assert abs(result.total_cost_usd - 0.3) < 1e-9
