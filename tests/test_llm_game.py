"""Integration tests for async run_llm_game with WS6 logging and checkpoint/resume (WS3 P5c)."""

import asyncio
import json
import re
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

class MemoryCSXMLPolicy:
    """Deterministic WS4 proposals for runner integration tests."""

    def __init__(self, tendencies=None):
        self.base = LegalXMLPolicy()
        self.tendencies = tendencies

    def __call__(self, messages):
        xml = self.base(messages)
        observation = next(
            message["content"]
            for message in messages
            if message["role"] == "user"
            and "[OWN STATE]" in message["content"]
        )
        player = re.search(
            r"^Player:\s*([AB]\d+)", observation, re.MULTILINE
        ).group(1)
        event = int(re.search(
            r"^Event:\s*(\d+)", observation, re.MULTILINE
        ).group(1))

        # Only A1 writes, making proposal order predictable.
        if player != "A1":
            return xml

        # Events 1–4 fill the group; 5 merges; 6 causes eviction.
        if self.tendencies is not None:
            tendency = self.tendencies[event - 1]
        else:
            tendency = (
                "Observation 1" if event == 5 else f"Observation {event}"
            )
        extra = (
            f'<MEMORY_UPDATE opponent="B1" '
            f'category="offensive_tendency" tendency="{tendency}"/>\n'
            f'<CS_UPDATE side="offense" '
            f'opponent_strategy="Zone defense" '
            f'counter_strategy="Counter at event {event}"/>\n'
        )
        return xml.replace("</RESPONSE>", extra + "</RESPONSE>")


def test_ws4_logging_and_checkpoint_replay(tmp_path):
    sim_cfg, llm_cfg = _get_test_configs()
    sim_cfg = sim_cfg.model_copy(update={
        "rules": sim_cfg.rules.model_copy(update={
            "target_score": 100,
            "game_length_s": 600,
        })
    })

    options = {
        "seed": 44,
        "sim_config": sim_cfg,
        "llm_config": llm_cfg,
        "max_events": 8,
    }

    resumed_path = tmp_path / "ws4_resumed.jsonl"
    failing_client = QuotaAfterNBackend(max_calls=8)
    failing_client.inner = FakeLLM(MemoryCSXMLPolicy())

    with pytest.raises(QuotaExceededError):
        run(run_llm_game(
            llm=failing_client,
            path=resumed_path,
            **options,
        ))

    checkpoint = json.loads(
        resumed_path.with_suffix(".ckpt.json").read_text(encoding="utf-8")
    )
    assert len(checkpoint["events"]) == 1

    resumed = run(run_llm_game(
        llm=FakeLLM(MemoryCSXMLPolicy()),
        path=resumed_path,
        resume=True,
        **options,
    ))

    clean_path = tmp_path / "ws4_clean.jsonl"
    clean = run(run_llm_game(
        llm=FakeLLM(MemoryCSXMLPolicy()),
        path=clean_path,
        **options,
    ))

    assert resumed["events"] == clean["events"] == 8
    assert resumed["score"] == clean["score"]

    # Parsing through the log reader validates the record schemas.
    resumed_records = read_game_log(resumed_path).records
    clean_records = read_game_log(clean_path).records

    def coordination_records(records):
        kinds = {
            "memory_proposal", "memory_write",
            "cs_proposal", "cs_write",
        }
        return [
            record.model_dump(mode="json")
            for record in records
            if record.record_type in kinds
        ]

    assert coordination_records(resumed_records) == coordination_records(
        clean_records
    )

    # Verify that replay also reconstructs what players actually saw.
    def observations(records):
        return [
            (record.event_idx, record.player, record.observation_text)
            for record in records
            if record.record_type == "decision"
        ]

    assert observations(resumed_records) == observations(clean_records)

    memory_writes = [
        record for record in clean_records
        if record.record_type == "memory_write"
    ]
    assert memory_writes
    assert all(
        record.visible_at == record.event_idx + 1
        for record in memory_writes
    )
    assert any(record.evicted_ids for record in memory_writes)

    cs_proposals = [
        record for record in clean_records
        if record.record_type == "cs_proposal"
    ]
    assert any(record.accepted and record.merged for record in cs_proposals)

def test_ws4_capacity_rejection_is_logged(tmp_path):
    sim_cfg, llm_cfg = _get_test_configs()
    sim_cfg = sim_cfg.model_copy(update={
        "rules": sim_cfg.rules.model_copy(update={
            "target_score": 100,
            "game_length_s": 600,
        })
    })

    tendencies = [
        "Observation 1",
        "Observation 2",
        "Observation 3",
        "Observation 4",
        # Reinforce all four entries to confidence 2.
        "Observation 1",
        "Observation 2",
        "Observation 3",
        "Observation 4",
        # Confidence 1: weaker than every stored entry.
        "Weaker fifth observation",
    ]

    path = tmp_path / "ws4_rejected.jsonl"
    result = run(run_llm_game(
        llm=FakeLLM(MemoryCSXMLPolicy(tendencies=tendencies)),
        path=path,
        seed=44,
        sim_config=sim_cfg,
        llm_config=llm_cfg,
        max_events=9,
    ))

    assert result["events"] == 9
    assert result["parse_failure_rate"] == 0.0

    records = read_game_log(path).records
    proposals = [
        record for record in records
        if record.record_type == "memory_proposal"
        and record.player == "A1"
    ]

    assert len(proposals) == 9
    assert all(record.accepted for record in proposals[:8])

    rejected = proposals[-1]
    assert rejected.event_idx == 9
    assert not rejected.accepted
    assert rejected.new_id is None
    assert rejected.merged_into is None

    writes = [
        record for record in records
        if record.record_type == "memory_write"
    ]
    assert len(writes) == 8
    assert not any(record.event_idx == 9 for record in writes)

    # A rejected memory proposal must not prevent the CS update.
    assert any(
        record.record_type == "cs_write"
        and record.event_idx == 9
        for record in records
    )

def test_runner_passes_embedder_to_memory_store(tmp_path):
    sim_cfg, llm_cfg = _get_test_configs()
    sim_cfg = sim_cfg.model_copy(update={
        "rules": sim_cfg.rules.model_copy(update={
            "game_length_s": 600,
        })
    })
    embedded_texts = []

    def embed(text):
        embedded_texts.append(text)
        return [1.0, 0.0]

    path = tmp_path / "ws4_embeddings.jsonl"
    result = run(run_llm_game(
        llm=FakeLLM(MemoryCSXMLPolicy()),
        path=path,
        seed=44,
        sim_config=sim_cfg,
        llm_config=llm_cfg,
        max_events=3,
        embedder=embed,
        similarity_threshold=0.80,
    ))

    assert result["events"] == 3
    assert "Observation 1" in embedded_texts
    assert "Observation 2" in embedded_texts

    proposals = [
        record
        for record in read_game_log(path).records
        if record.record_type == "memory_proposal"
        and record.player == "A1"
    ]

    assert len(proposals) == 3
    memory_id = proposals[0].new_id
    assert memory_id is not None
    assert proposals[1].merged_into == memory_id
    assert proposals[2].merged_into == memory_id
    assert proposals[2].confidence_after == 3

    start = next(
        record
        for record in read_game_log(path).records
        if record.record_type == "game_start"
    )
    settings = start.config_snapshot["memory_settings"]
    assert settings["backend"] == "embedding"
    assert settings["similarity_threshold"] == 0.80
    assert settings["model"].endswith("embed")

def test_checkpoint_rejects_changed_embedding_settings(tmp_path):
    sim_cfg, llm_cfg = _get_test_configs()
    path = tmp_path / "ws4_checkpoint_mismatch.jsonl"

    def embed(text):
        return [1.0, 0.0]

    options = {
        "path": path,
        "seed": 44,
        "sim_config": sim_cfg,
        "llm_config": llm_cfg,
        "embedder": embed,
    }

    failing_client = QuotaAfterNBackend(max_calls=8)
    failing_client.inner = FakeLLM(MemoryCSXMLPolicy())

    with pytest.raises(QuotaExceededError):
        run(run_llm_game(
            llm=failing_client,
            similarity_threshold=0.80,
            **options,
        ))

    checkpoint_path = path.with_suffix(".ckpt.json")
    assert checkpoint_path.exists()

    original_log = path.read_bytes()
    original_checkpoint = checkpoint_path.read_bytes()
    resumed_client = FakeLLM(MemoryCSXMLPolicy())

    with pytest.raises(ValueError, match="Checkpoint configuration"):
        run(run_llm_game(
            llm=resumed_client,
            similarity_threshold=0.90,
            resume=True,
            **options,
        ))

    assert resumed_client.calls == []
    assert path.read_bytes() == original_log
    assert checkpoint_path.read_bytes() == original_checkpoint