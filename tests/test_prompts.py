"""Unit tests for WS3 PromptBuilder and Jinja2 templates (P3)."""

import shutil
from pathlib import Path

import pytest
from jinja2 import UndefinedError

from bball3x3.agents.observation import build_observation
from bball3x3.agents.prompting import DEFAULT_PROMPTS_DIR, PromptBuilder
from bball3x3.config import SimulationConfig, load_roster_config
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.state import create_initial_state
from bball3x3.schemas.agent import CoordinationConfig

TEAM_CONDITIONS = {
    "A_full": CoordinationConfig(comms=True, captain=True, memory_write=True),
    "B_no_comms": CoordinationConfig(comms=False, captain=True, memory_write=True),
    "C_no_captain": CoordinationConfig(comms=True, captain=False, memory_write=True),
    "D_no_mem_write": CoordinationConfig(comms=True, captain=True, memory_write=False),
}


def test_variant_matrix_renders_and_system_prompt_is_static_per_player():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1), first_possession="A")
    roster = load_roster_config()
    builder = PromptBuilder(roster=roster)

    for label, flags in TEAM_CONDITIONS.items():
        for is_captain in (True, False):
            # Offense (A1 ball handler, A2 off-ball) and Defense (B1)
            for pid in ("A1", "A2", "B1"):
                obs = build_observation(state, pid, flags=flags, is_captain=is_captain)
                msgs, obs_text, p_hash = builder.build(obs)
                assert len(msgs) == 2
                assert msgs[0]["role"] == "system"
                assert msgs[1]["role"] == "user"
                assert obs_text in msgs[1]["content"]
                assert len(p_hash) == 64

                # Check flag-specific content
                if is_captain and flags.captain:
                    assert "[CAPTAIN ADDENDUM]" in msgs[0]["content"]
                else:
                    assert "[CAPTAIN ADDENDUM]" not in msgs[0]["content"]

                if not flags.comms:
                    assert "Teammate messaging `<MESSAGES>` is disabled" in msgs[1]["content"]
                if not flags.memory_write:
                    assert "MEMORY_UPDATE" not in msgs[1]["content"]


def test_template_hash_stable_and_changes_on_template_edit(tmp_path: Path):
    custom_dir = tmp_path / "prompts"
    shutil.copytree(DEFAULT_PROMPTS_DIR, custom_dir)

    b1 = PromptBuilder(custom_dir)
    b2 = PromptBuilder(custom_dir)
    h1 = b1.template_hash(CoordinationConfig(), is_captain=True)
    assert h1 == b2.template_hash(CoordinationConfig(), is_captain=True)

    # Different variant gives different hash
    h_non_cap = b1.template_hash(CoordinationConfig(), is_captain=False)
    assert h1 != h_non_cap

    # Editing a template changes the hash
    inst_file = custom_dir / "instruction.j2"
    inst_file.write_text(inst_file.read_text(encoding="utf-8") + "\n# modified\n", encoding="utf-8")
    b3 = PromptBuilder(custom_dir)
    assert b3.template_hash(CoordinationConfig(), is_captain=True) != h1


def test_strict_undefined_catches_missing_variable(tmp_path: Path):
    custom_dir = tmp_path / "prompts"
    shutil.copytree(DEFAULT_PROMPTS_DIR, custom_dir)
    inst_file = custom_dir / "instruction.j2"
    inst_file.write_text(
        inst_file.read_text(encoding="utf-8") + "\n{{ non_existent_var }}\n",
        encoding="utf-8",
    )
    builder = PromptBuilder(custom_dir)
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1), first_possession="A")
    obs = build_observation(state, "A1")
    with pytest.raises(UndefinedError):
        builder.build(obs)
