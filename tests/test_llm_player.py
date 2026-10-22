"""Unit tests for LLMPlayer, adapter, and FakeLLM policies (WS3 P4)."""

import asyncio

import pytest

from bball3x3.agents.adapter import build_decision_record, legalize_decision
from bball3x3.agents.llm_player import LLMPlayer
from bball3x3.agents.observation import build_observation
from bball3x3.config import LLMPlayersConfig, SimulationConfig
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.state import create_initial_state
from bball3x3.llm import BudgetExceededError, FakeLLM
from bball3x3.llm.base import LLMResponse
from bball3x3.llm.fake_policies import FaultInjectingPolicy, LegalXMLPolicy


def run(coro):
    return asyncio.run(coro)


def test_llm_player_bad_then_good_repairs_and_sums_tokens_and_cost():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1), first_possession="A")
    obs = build_observation(state, "A1", is_captain=True)

    class AccountingFakeLLM:
        def __init__(self, replies):
            self.replies = list(replies)

        async def complete(self, messages, params, response_format=None):
            _ = (messages, response_format)
            text, pt, ct, cost, lat = self.replies.pop(0)
            return LLMResponse(
                text=text,
                model=params.model,
                prompt_tokens=pt,
                completion_tokens=ct,
                cost_usd=cost,
                latency_ms=lat,
            )

    llm = AccountingFakeLLM(
        [
            ("oops forgot xml", 100, 10, 0.001, 50.0),
            ('<RESPONSE><ACTION type="PASS" target="A2"/></RESPONSE>', 120, 15, 0.002, 60.0),
        ]
    )
    player = LLMPlayer("A1", llm, LLMPlayersConfig(repair_attempts=1))
    res = run(player.decide(obs))

    assert res.kept.parse_ok is True
    assert res.kept.action == "PASS"
    assert res.kept.target == "A2"
    assert len(res.responses) == 2
    assert res.prompt_tokens == 220
    assert res.completion_tokens == 25
    assert res.total_tokens == 245
    assert res.cost_usd == pytest.approx(0.003)
    assert res.latency_ms == pytest.approx(110.0)

    fixed, remap = legalize_decision(state, "A1", res)
    assert remap is None
    rec = build_decision_record(
        event_idx=1, player_id="A1", result=res, fixed=fixed, remap=remap
    )
    assert rec.parse_ok is True
    assert rec.invalid_reason is None
    assert rec.executed_action == "PASS"
    assert rec.executed_target == "A2"
    assert rec.tokens == {"prompt": 220, "completion": 25, "total": 245}


def test_llm_player_bad_then_bad_produces_parse_fail_and_valid_decision_record():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1), first_possession="A")
    obs = build_observation(state, "A1")

    llm = FakeLLM(["not xml", "still not xml"])
    player = LLMPlayer("A1", llm, LLMPlayersConfig(repair_attempts=1))
    res = run(player.decide(obs))

    assert res.kept.parse_ok is False
    fixed, remap = legalize_decision(state, "A1", res)
    assert remap is not None
    assert remap.reason == "PARSE_FAIL"
    assert fixed.action == "HOLD"

    rec = build_decision_record(
        event_idx=1, player_id="A1", result=res, fixed=fixed, remap=remap
    )
    assert rec.parse_ok is False
    assert rec.parsed_output is None
    assert rec.invalid_reason == "PARSE_FAIL"
    assert rec.remapped_action == "HOLD"
    assert rec.executed_action == "HOLD"
    assert rec.raw_output == "still not xml"


def test_llm_player_budget_exceeded_propagates_and_does_not_mask_as_parse_fail():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1), first_possession="A")
    obs = build_observation(state, "A1")

    class FailingBudgetLLM:
        async def complete(self, messages, params, response_format=None):
            _ = (messages, params, response_format)
            raise BudgetExceededError("budget exhausted")

    player = LLMPlayer("A1", FailingBudgetLLM(), LLMPlayersConfig())
    with pytest.raises(BudgetExceededError):
        run(player.decide(obs))


def test_llm_player_json_mode_and_fake_policies():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1), first_possession="A")
    obs = build_observation(state, "A1")

    json_llm = FakeLLM(
        ['{"action": {"type": "SHOOT", "target": null, "memory_ref": null}, "rationale": "open"}']
    )
    player_json = LLMPlayer("A1", json_llm, LLMPlayersConfig(output_format="json"))
    res_json = run(player_json.decide(obs))
    assert res_json.kept.parse_ok is True
    assert res_json.kept.action == "SHOOT"
    assert json_llm.calls[0]["response_format"] is not None

    # LegalXMLPolicy and FaultInjectingPolicy
    policy = FaultInjectingPolicy(
        LegalXMLPolicy(), fail_every_n_decisions=1, recover_on_repair=True
    )
    fault_llm = FakeLLM(policy)
    player_xml = LLMPlayer("A1", fault_llm, LLMPlayersConfig(repair_attempts=1))
    res_fault = run(player_xml.decide(obs))
    assert res_fault.kept.parse_ok is True
    assert len(res_fault.responses) == 2
