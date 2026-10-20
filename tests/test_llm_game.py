"""Integration tests for async run_llm_game with WS6 logging and checkpoint/resume (WS3 P5c)."""

import asyncio
import json
from pathlib import Path

import pytest

from bball3x3.analysis import compute_game_metrics, read_game_log
from bball3x3.config import (
    LLMConfig,
    SimulationConfig,
    load_initial_memory_config,
    load_roster_config,
    load_simulation_config,
)
from bball3x3.llm import CallParams, FakeLLM, LLMResponse, QuotaExceededError
from bball3x3.llm.fake_policies import FaultInjectingPolicy, LegalXMLPolicy
from bball3x3.runner.llm_game import run_llm_game
from bball3x3.schemas.agent import CoordinationConfig


def run(coro):
    return asyncio.run(coro)


def _get_test_configs() -> tuple[SimulationConfig, LLMConfig]:
    sim_cfg = load_simulation_config()
    sim_cfg = sim_cfg.model_copy(
        update={
            "rules": sim_cfg.rules.model_copy(
                update={"target_score": 5, "game_length_s": 60}
            )
        }
    )
    llm_cfg = LLMConfig()
    return sim_cfg, llm_cfg


def test_run_llm_game_legal_xml_policy(tmp_path: Path):
    sim_cfg, llm_cfg = _get_test_configs()
    client = FakeLLM(LegalXMLPolicy())
    log_path = tmp_path / "game_legal.jsonl"

    result = run(
        run_llm_game(
            llm=client,
            path=log_path,
            seed=42,
            sim_config=sim_cfg,
            llm_config=llm_cfg,
            roster_config=load_roster_config(),
            initial_memory_config=load_initial_memory_config(),
        )
    )

    assert result["game_complete"] is True
    assert result["parse_failure_rate"] == 0.0
    assert result["iar"] == 0.0
    assert log_path.exists()

    index = read_game_log(log_path)
    assert index.is_complete

    metrics = compute_game_metrics(index)
    assert metrics.game_complete
    assert metrics.iar_game.rate == 0.0
    assert metrics.iar["A"].rate == 0.0
    assert metrics.iar["B"].rate == 0.0
    assert metrics.sir.rate == 0.0


def test_run_llm_game_fault_injecting_policy(tmp_path: Path):
    sim_cfg, llm_cfg = _get_test_configs()
    policy = FaultInjectingPolicy(
        LegalXMLPolicy(), fail_every_n_decisions=3, recover_on_repair=False
    )
    client = FakeLLM(policy)
    log_path = tmp_path / "game_fault.jsonl"

    result = run(
        run_llm_game(
            llm=client,
            path=log_path,
            seed=43,
            sim_config=sim_cfg,
            llm_config=llm_cfg,
            coordination={
                "A": CoordinationConfig(comms=False),
                "B": CoordinationConfig(comms=True, memory=False, cs=False),
            },
            team_conditions={"A": "B_no_comm", "B": "C_comm_only"},
        )
    )

    assert result["game_complete"] is True
    assert result["parse_failure_rate"] > 0.0
    assert result["iar"] > 0.0

    index = read_game_log(log_path)
    metrics = compute_game_metrics(index)
    assert metrics.game_complete
    assert metrics.iar_game.rate is not None and metrics.iar_game.rate > 0.0
    assert metrics.sir.rate == 0.0


class QuotaAfterNBackend:
    def __init__(self, max_calls: int):
        self.inner = FakeLLM(LegalXMLPolicy())
        self.max_calls = max_calls
        self.calls = 0

    async def complete(
        self,
        messages: list[dict[str, str]],
        params: CallParams,
        response_format: dict | None = None,
    ) -> LLMResponse:
        self.calls += 1
        if self.calls > self.max_calls:
            raise QuotaExceededError("Daily quota reached")
        return await self.inner.complete(
            messages,
            params,
            response_format=response_format,
        )


def test_run_llm_game_checkpoint_and_resume(tmp_path: Path):
    sim_cfg, llm_cfg = _get_test_configs()
    log_path = tmp_path / "game_resume.jsonl"
    ckpt_path = log_path.with_suffix(".ckpt.json")

    # Stop partway through event 2 (8 calls = 6 for event 1 + 2 into event 2)
    failing_client = QuotaAfterNBackend(max_calls=8)
    with pytest.raises(QuotaExceededError):
        run(
            run_llm_game(
                llm=failing_client,
                path=log_path,
                seed=44,
                sim_config=sim_cfg,
                llm_config=llm_cfg,
            )
        )

    assert ckpt_path.exists()
    ckpt_data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert len(ckpt_data["events"]) == 1

    # Resume with a fresh client and compare with an uninterrupted run
    resumed_client = FakeLLM(LegalXMLPolicy())
    resumed_result = run(
        run_llm_game(
            llm=resumed_client,
            path=log_path,
            seed=44,
            sim_config=sim_cfg,
            llm_config=llm_cfg,
            resume=True,
        )
    )
    assert not ckpt_path.exists()

    clean_log_path = tmp_path / "game_clean.jsonl"
    clean_client = FakeLLM(LegalXMLPolicy())
    clean_result = run(
        run_llm_game(
            llm=clean_client,
            path=clean_log_path,
            seed=44,
            sim_config=sim_cfg,
            llm_config=llm_cfg,
        )
    )

    assert resumed_result["score"] == clean_result["score"]
    assert resumed_result["events"] == clean_result["events"]
    assert resumed_result["end_reason"] == clean_result["end_reason"]

    resumed_index = read_game_log(log_path)
    clean_index = read_game_log(clean_log_path)
    assert len(resumed_index.records) == len(clean_index.records)
