import asyncio

import pytest

from bball3x3.config import LLMPlayersConfig
from bball3x3.llm import FakeLLM, LLMResponse

PARAMS = LLMPlayersConfig(model="fake/model")
MSGS = [{"role": "user", "content": "you are A1"}]


def test_fake_llm_returns_scripted_replies_in_order():
    llm = FakeLLM(["<RESPONSE>1</RESPONSE>", "<RESPONSE>2</RESPONSE>"])
    first = asyncio.run(llm.complete(MSGS, PARAMS))
    second = asyncio.run(llm.complete(MSGS, PARAMS))
    assert isinstance(first, LLMResponse)
    assert first.text == "<RESPONSE>1</RESPONSE>"
    assert second.text == "<RESPONSE>2</RESPONSE>"
    assert first.model == "fake/model"


def test_fake_llm_responder_function_sees_messages():
    llm = FakeLLM(lambda messages: f"echo:{messages[-1]['content']}")
    resp = asyncio.run(llm.complete(MSGS, PARAMS))
    assert resp.text == "echo:you are A1"


def test_fake_llm_records_calls():
    llm = FakeLLM(["a"])
    asyncio.run(llm.complete(MSGS, PARAMS, response_format={"type": "json_object"}))
    assert llm.calls == [
        {"messages": MSGS, "model": "fake/model", "response_format": {"type": "json_object"}}
    ]


def test_fake_llm_errors_when_script_runs_out():
    llm = FakeLLM(["only one"])
    asyncio.run(llm.complete(MSGS, PARAMS))
    with pytest.raises(RuntimeError, match="no scripted reply"):
        asyncio.run(llm.complete(MSGS, PARAMS))
