import asyncio
import json

from typer.testing import CliRunner

from bball3x3.analysis import read_game_log
from bball3x3.cli import app
from bball3x3.config import ExperimentConfig, LLMConfig, load_simulation_config
from bball3x3.llm import FakeLLM
from bball3x3.llm.budget import BudgetTracker
from bball3x3.llm.fake_policies import LegalXMLPolicy
from bball3x3.runner.experiment import is_complete, plan_games, run_experiment


def _exp(**overrides):
    data = {
        "experiment_id": "exp_test",
        "matchup": {
            "home": {"label": "A_full", "coordination": {}},
            "away": {"label": "B_no_comm", "coordination": {"comms": False}},
        },
        "seeds": [7],
        "max_concurrent_games": 2,
    }
    return ExperimentConfig(**{**data, **overrides})


def _sim():
    sim = load_simulation_config()
    return sim.model_copy(update={"rules": sim.rules.model_copy(
        update={"target_score": 5, "game_length_s": 60}
    )})


def _run(exp, out, llm, **options):
    return asyncio.run(run_experiment(
        exp, llm=llm, llm_config=LLMConfig(), out_dir=out, sim_config=_sim(), **options,
    ))


def test_plan_swaps_first_possession_per_seed(tmp_path):
    specs = plan_games(_exp(seeds=[1, 2]), tmp_path)
    assert [(s.seed, s.first_possession) for s in specs] == [
        (1, "A"), (1, "B"), (2, "A"), (2, "B"),
    ]
    assert len({s.game_id for s in specs}) == 4
    coin = plan_games(_exp(swap_first_possession=False), tmp_path)
    assert [(s.first_possession, s.game_id) for s in coin] == [(None, "exp_test_s7_coin")]


def test_experiment_plays_paired_games_with_team_flags(tmp_path):
    result = _run(_exp(), tmp_path, FakeLLM(LegalXMLPolicy()))
    assert result["errors"] == []
    assert {g["status"] for g in result["games"].values()} == {"complete"}
    starts = {}
    for spec in plan_games(_exp(), tmp_path):
        start = read_game_log(spec.path).by_type["game_start"][0]
        starts[start.first_possession] = start
    assert set(starts) == {"A", "B"}
    for start in starts.values():
        assert start.experiment_id == "exp_test" and start.seed == 7
        assert start.team_conditions == {"A": "A_full", "B": "B_no_comm"}
        assert start.coordination["A"].comms is True
        assert start.coordination["B"].comms is False
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert set(manifest["games"]) == {"exp_test_s7_A", "exp_test_s7_B"}


def test_rerun_skips_finished_games(tmp_path):
    _run(_exp(), tmp_path, FakeLLM(LegalXMLPolicy()))
    unused = FakeLLM(LegalXMLPolicy())
    result = _run(_exp(), tmp_path, unused)
    assert unused.calls == []
    assert {g["status"] for g in result["games"].values()} == {"complete"}


def test_unfinished_game_is_stopped_and_resumable(tmp_path):
    result = _run(_exp(seeds=[3]), tmp_path, FakeLLM(LegalXMLPolicy()), max_events=1)
    assert {g["status"] for g in result["games"].values()} == {"stopped"}
    for spec in plan_games(_exp(seeds=[3]), tmp_path):
        assert spec.path.with_suffix(".ckpt.json").exists()
        assert not is_complete(spec.path)


def test_earlier_spend_counts_toward_budget(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"spent_usd": 0.5, "games": {}}))
    budget = BudgetTracker(max_usd=10.0)
    result = _run(_exp(), tmp_path, FakeLLM(LegalXMLPolicy()), budget=budget)
    assert budget.spent_usd == 0.5
    assert result["spent_usd"] == 0.5


def test_cli_dry_run_lists_games_without_calling_models(tmp_path):
    result = CliRunner().invoke(app, [
        "run-experiment", "configs/experiments/pilot.yaml", "--out", str(tmp_path), "--dry-run",
    ])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert len(lines) == 6
    assert all(line.startswith("todo") for line in lines)
