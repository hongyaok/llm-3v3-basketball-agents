"""The async LLM referee affects logged games and preserves its trace."""

import json

import pytest

from bball3x3.agents.base import BasePlayer
from bball3x3.analysis.log_reader import read_game_log
from bball3x3.config import LLMConfig, LLMRefereeConfig
from bball3x3.engine.contact import referee_query_text
from bball3x3.llm import FakeLLM
from bball3x3.referee import LLMReferee, RetrievalResult, RetrievedRule
from bball3x3.runner.game import run_logged_game
from bball3x3.schemas.actions import ActionProposal

NONE_XML = (
    '<REFEREE_DECISION call="NONE" foul="FALSE" offender="NONE" '
    'fouled_player="NONE" foul_type="NONE" violation_type="NONE" rules=""/>'
)


class HoldPlayer(BasePlayer):
    def decide(self, state, **kwargs):
        return ActionProposal(player_id=self.player_id, action="HOLD")


class StubRetriever:
    backend = "hash"
    model_name = "hashed-unigrams-v1-128"

    def retrieve(self, state, *, top_k):
        assert top_k == 3
        return RetrievalResult(
            query=referee_query_text(state),
            categories=("stalling",),
            rules=(RetrievedRule(
                "R29.1", "stalling", "A team may not stall", 20, 20, 0.9,
            ),),
        )


def _llm_config(*, enabled=True, backend="llm"):
    return LLMConfig(referee=LLMRefereeConfig(enabled=enabled, backend=backend))


def _stalling_reply(messages):
    content = messages[-1]["content"]
    state_json = content.split("[REFEREE_STATE]\n", 1)[1].split(
        "\n[DETERMINISTIC_QUERY]", 1,
    )[0]
    offender = f"{json.loads(state_json)['possession']}1"
    return (
        f'<REFEREE_DECISION call="VIOLATION" foul="FALSE" offender="{offender}" '
        'fouled_player="NONE" foul_type="NONE" violation_type="STALLING" '
        'rules="R29.1"/>'
    )


def test_configured_llm_call_changes_game_and_is_logged(tmp_path):
    fake = FakeLLM(_stalling_reply)
    path = tmp_path / "llm.jsonl"

    result = run_logged_game(
        seed=17, path=path, max_events=1, agent_factory=HoldPlayer,
        llm_config=_llm_config(), llm_backend=fake, rule_retriever=StubRetriever(),
    )

    log = read_game_log(path)
    start = log.by_type["game_start"][0]
    record = log.by_type["referee"][0]
    state = log.by_type["state"][0].state
    assert result["events"] == 1
    assert len(fake.calls) == 1
    assert record.decision.call == "VIOLATION"
    assert record.decision.violation_type == "STALLING"
    assert record.decision.rule_ids_cited == ["R29.1"]
    assert record.retrieved_chunk_ids == ["R29.1"]
    assert record.query.startswith("event=HOLD;")
    assert record.raw_output == _stalling_reply(fake.calls[0]["messages"])
    assert record.failure_code is None
    assert state.offense != start.first_possession
    assert start.config_snapshot["llm_referee"]["backend"] == "llm"
    assert start.config_snapshot["rule_index"]["model"] == StubRetriever.model_name
    assert "referee" in start.prompt_hashes


def test_malformed_llm_reply_is_logged_and_does_not_change_game(tmp_path):
    llm_path = tmp_path / "llm-bad.jsonl"
    baseline_path = tmp_path / "baseline.jsonl"
    run_logged_game(
        seed=17, path=llm_path, max_events=1, agent_factory=HoldPlayer,
        llm_config=_llm_config(), llm_backend=FakeLLM(["bad xml"]),
        rule_retriever=StubRetriever(),
    )
    run_logged_game(
        seed=17, path=baseline_path, max_events=1, agent_factory=HoldPlayer,
    )
    bad = read_game_log(llm_path)
    baseline = read_game_log(baseline_path)

    record = bad.by_type["referee"][0]
    assert record.decision.call == "NONE"
    assert record.failure_code == "REF_PARSE_FAIL"
    assert record.parse_error
    assert record.raw_output == "bad xml"
    assert record.retrieved_chunk_ids == ["R29.1"]
    assert bad.by_type["state"][0].state == baseline.by_type["state"][0].state


@pytest.mark.parametrize(("enabled", "backend"), [(False, "llm"), (True, "rule_based")])
def test_disabled_config_keeps_rule_based_referee_and_skips_llm(tmp_path, enabled, backend):
    fake = FakeLLM([NONE_XML])
    path = tmp_path / "disabled.jsonl"
    run_logged_game(
        seed=17, path=path, max_events=1, agent_factory=HoldPlayer,
        llm_config=_llm_config(enabled=enabled, backend=backend), llm_backend=fake,
    )
    log = read_game_log(path)
    assert not fake.calls
    assert log.by_type["referee"][0].raw_output is None
    assert "llm_referee" not in log.by_type["game_start"][0].config_snapshot


def test_explicit_llm_referee_is_accepted_without_llm_config(tmp_path):
    path = tmp_path / "explicit.jsonl"
    referee = LLMReferee(FakeLLM([NONE_XML]), StubRetriever())
    run_logged_game(
        seed=17, path=path, max_events=1, agent_factory=HoldPlayer,
        referee=referee,
    )
    assert read_game_log(path).by_type["referee"][0].raw_output == NONE_XML


def test_rebound_branch_keeps_llm_trace(tmp_path):
    path = tmp_path / "rebound.jsonl"
    run_logged_game(
        seed=17, path=path, max_events=80,
        llm_config=_llm_config(), llm_backend=FakeLLM(lambda _messages: NONE_XML),
        rule_retriever=StubRetriever(),
    )
    records = read_game_log(path).by_type["referee"]
    assert any(record.query.startswith("event=REBOUND;") for record in records)
    assert all(record.raw_output == NONE_XML for record in records)


def test_backend_failure_closes_game_and_propagates(tmp_path):
    path = tmp_path / "failed.jsonl"
    with pytest.raises(RuntimeError, match="no scripted reply"):
        run_logged_game(
            seed=17, path=path, max_events=2, agent_factory=HoldPlayer,
            llm_config=_llm_config(), llm_backend=FakeLLM([NONE_XML]),
            rule_retriever=StubRetriever(),
        )
    # An unfinished log remains readable after the adapter and logger close.
    assert len(read_game_log(path).by_type["referee"]) == 1
