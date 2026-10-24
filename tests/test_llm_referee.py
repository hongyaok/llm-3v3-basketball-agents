"""The Phase B LLM decision layer is strict, grounded, and failure-safe."""

import asyncio
from types import SimpleNamespace

import pytest

from bball3x3.config import LLMRefereeConfig
from bball3x3.referee import (
    LLMReferee,
    RetrievalResult,
    RetrievedRule,
    parse_referee_xml,
)
from bball3x3.referee.validation import make_state
from bball3x3.schemas.log import RefereeRecord


def _xml(**overrides):
    fields = {
        "call": "NONE",
        "foul": "FALSE",
        "offender": "NONE",
        "fouled_player": "NONE",
        "foul_type": "NONE",
        "violation_type": "NONE",
        "rules": "",
    }
    fields.update(overrides)
    attrs = " ".join(f'{key}="{value}"' for key, value in fields.items())
    return f"<REFEREE_DECISION {attrs}/>"


class StubRetriever:
    def __init__(self):
        self.calls = []

    def retrieve(self, state, *, top_k):
        self.calls.append((state, top_k))
        return RetrievalResult(
            query="deterministic screen query",
            categories=("screening",),
            rules=(
                RetrievedRule("R33.7", "screening", "Moving screen is illegal", 28, 29, 0.9),
                RetrievedRule("R33.1", "screening", "Legal contact", 27, 28, 0.5),
            ),
        )


class StubBackend:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def complete(self, messages, params, response_format=None):
        self.calls.append((messages, params, response_format))
        return SimpleNamespace(
            text=self.reply, model="fake-referee", prompt_tokens=50,
            completion_tokens=25, cost_usd=0.02, latency_ms=123.0,
            cached=False, attempts=1,
        )


def _screen_state():
    return make_state(
        actions={"A2": "SCREEN"},
        contact_type="SCREEN_CONTACT", involved=("A2", "B2"),
        event={"event_type": "SCREEN"},
    )


def test_llm_referee_sends_state_query_excerpts_and_parses_call():
    reply = _xml(
        call="FOUL", foul="TRUE", offender="A2", fouled_player="B2",
        foul_type="OFFENSIVE_FOUL", rules="R33.7",
    )
    backend = StubBackend(reply)
    retriever = StubRetriever()
    referee = LLMReferee(backend, retriever)
    state = _screen_state()

    result = asyncio.run(referee.judge_with_trace(state))

    assert result.parse_ok
    assert result.failure_code is None
    assert result.decision.call == "FOUL"
    assert result.decision.offender == "A2"
    assert result.decision.fouled_player == "B2"
    assert result.decision.rule_ids_cited == ["R33.7"]
    assert result.retrieved_chunk_ids == ("R33.7", "R33.1")
    assert result.raw_output == reply
    assert result.cost_usd == 0.02
    assert result.latency_ms == 123.0
    assert result.prompt_tokens == 50
    assert retriever.calls == [(state, 3)]
    messages, params, response_format = backend.calls[0]
    assert params.temperature == 0.0
    assert response_format is None
    assert messages[0]["role"] == "system"
    assert '"contact_detected": true' in messages[1]["content"]
    assert "deterministic screen query" in messages[1]["content"]
    assert "R33.7" in messages[1]["content"]
    assert "Moving screen is illegal" in messages[1]["content"]
    assert asyncio.run(referee.judge(state)).call == "FOUL"


@pytest.mark.parametrize("reply", ["```xml\n" + _xml() + "\n```", "```\n" + _xml() + "\n```"])
def test_single_fence_around_valid_output_is_accepted(reply):
    result = asyncio.run(LLMReferee(StubBackend(reply), StubRetriever()).judge_with_trace(
        _screen_state()
    ))
    assert result.failure_code is None
    assert result.decision.call == "NONE"
    assert result.raw_output == reply


@pytest.mark.parametrize("reply", [
    "garbage",
    "Here is my call:\n```xml\n" + _xml() + "\n```",
    _xml(call="FOUL", foul="TRUE", offender="A2", fouled_player="B2",
         foul_type="OFFENSIVE_FOUL", rules="R999"),
    _xml(call="FOUL", foul="TRUE", offender="A2", fouled_player="B2",
         foul_type="OFFENSIVE_FOUL", rules=""),
    _xml(call="FOUL", foul="TRUE", offender="B2", fouled_player="B3",
         foul_type="DEFENSIVE_FOUL", rules="R33.7"),
    _xml(call="FOUL", foul="FALSE", offender="A2", fouled_player="B2",
         foul_type="OFFENSIVE_FOUL", rules="R33.7"),
    _xml(call="VIOLATION", offender="A2", violation_type="SHOT_CLOCK", rules="R33.7"),
    _xml(call="NONE", rules="R33.7"),
    _xml(call="FOUL", foul="TRUE", offender="A2", fouled_player="B2",
         foul_type="OFFENSIVE_FOUL", rules="R33.7,R33.7"),
])
def test_malformed_or_ungrounded_output_becomes_none_with_parse_failure(reply):
    result = asyncio.run(LLMReferee(StubBackend(reply), StubRetriever()).judge_with_trace(
        _screen_state()
    ))
    assert result.decision.call == "NONE"
    assert result.failure_code == "REF_PARSE_FAIL"
    assert result.parse_error
    assert result.raw_output == reply
    assert result.retrieved_chunk_ids == ("R33.7", "R33.1")
    record = result.as_log_record(1)
    assert record.failure_code == "REF_PARSE_FAIL"
    assert record.raw_output == reply
    assert record.retrieved_chunk_ids == ["R33.7", "R33.1"]
    assert RefereeRecord.model_validate_json(record.model_dump_json()) == record


def test_none_and_judgement_violation_are_supported():
    state = _screen_state()
    none = parse_referee_xml(_xml(), state, ("R33.7",))
    assert none.call == "NONE"
    violation = parse_referee_xml(
        _xml(call="VIOLATION", offender="B2", violation_type="GOALTENDING", rules="R33.7"),
        state, ("R33.7",),
    )
    assert violation.call == "VIOLATION"
    assert violation.violation_type == "GOALTENDING"


def test_objective_event_cannot_become_a_referee_call():
    state = make_state(event={"event_type": "SHOT_CLOCK", "objective_violation": True})
    reply = _xml(
        call="VIOLATION", offender="A1", violation_type="STALLING", rules="R33.7",
    )
    result = asyncio.run(LLMReferee(StubBackend(reply), StubRetriever()).judge_with_trace(state))
    assert result.decision.call == "NONE"
    assert result.failure_code == "REF_PARSE_FAIL"


def test_backend_error_propagates_instead_of_being_misreported_as_parse_failure():
    class FailingBackend:
        async def complete(self, messages, params, response_format=None):
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(LLMReferee(FailingBackend(), StubRetriever()).judge_with_trace(
            _screen_state()
        ))


@pytest.mark.parametrize("config", [
    LLMRefereeConfig(output_format="json"),
    LLMRefereeConfig(temperature=0.5),
    LLMRefereeConfig(top_k_rules=2),
])
def test_requires_phase_b_xml_zero_temperature_and_top_three(config):
    with pytest.raises(ValueError):
        LLMReferee(StubBackend(_xml()), StubRetriever(), config)
