"""Tests for EngineSession refactor (D1) and zone/direction target extensions (§3.8)."""

from pathlib import Path

from bball3x3.config import SimulationConfig
from bball3x3.engine.actions import format_legal_action_hint, remap_invalid_action, validate_action
from bball3x3.engine.court import ZONES
from bball3x3.engine.loop import play_heuristic_game
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.session import EngineSession
from bball3x3.engine.state import create_initial_state
from bball3x3.runner.game import run_logged_game
from bball3x3.schemas.actions import ActionProposal


def test_engine_session_matches_play_heuristic_game_byte_identical(tmp_path: Path):
    """D1 regression guard: seeds 7 and 101 must produce byte-identical payloads and logs."""
    for seed in (7, 101):
        p1 = tmp_path / f"seed_{seed}_a.jsonl"
        p2 = tmp_path / f"seed_{seed}_b.jsonl"
        r1 = run_logged_game(seed=seed, path=p1)
        r2 = run_logged_game(seed=seed, path=p2)
        assert r1["events"] == r2["events"]
        assert r1["score"] == r2["score"]
        assert p1.read_bytes() == p2.read_bytes()

        s1 = play_heuristic_game(seed=seed, collect_history=True)
        s2 = play_heuristic_game(seed=seed, collect_history=True)
        assert s1["score"] == s2["score"]
        assert s1["events"] == s2["events"]
        assert s1["violations"] == []
        assert len(s1["history"]) == s1["events"] + 1


def test_zone_and_direction_target_validation():
    config = SimulationConfig()
    state = create_initial_state(config, GameRNG.from_seed(42), first_possession="A")

    # Zone target on CUT is valid
    ok, reason, _ = validate_action(
        state, ActionProposal(player_id="A2", action="CUT", target="LEFT_CORNER")
    )
    assert ok is True
    assert reason is None

    # Unknown zone on CUT gives BAD_TARGET
    ok, reason, _ = validate_action(
        state, ActionProposal(player_id="A2", action="CUT", target="OUTER_SPACE")
    )
    assert ok is False
    assert reason == "BAD_TARGET"

    # Direction target on DRIVE is valid
    ok, reason, _ = validate_action(
        state, ActionProposal(player_id="A1", action="DRIVE", target="BASELINE")
    )
    assert ok is True
    assert reason is None

    # Bad direction on DRIVE gives BAD_TARGET
    ok, reason, _ = validate_action(
        state, ActionProposal(player_id="A1", action="DRIVE", target="UPWARDS")
    )
    assert ok is False
    assert reason == "BAD_TARGET"

    # SCREEN accepts both teammate and opponent targets
    ok1, _, _ = validate_action(
        state, ActionProposal(player_id="A2", action="SCREEN", target="A1")
    )
    ok2, _, _ = validate_action(
        state, ActionProposal(player_id="A2", action="SCREEN", target="B1")
    )
    assert ok1 is True
    assert ok2 is True

    # Optional opponent target on DEFEND / CONTEST / STEAL_ATTEMPT
    ok3, _, _ = validate_action(
        state, ActionProposal(player_id="B1", action="DEFEND", target=None)
    )
    ok4, _, _ = validate_action(
        state, ActionProposal(player_id="B1", action="DEFEND", target="A2")
    )
    ok5, reason5, _ = validate_action(
        state, ActionProposal(player_id="B1", action="DEFEND", target="B2")
    )
    assert ok3 is True
    assert ok4 is True
    assert ok5 is False
    assert reason5 == "BAD_TARGET"

    # Superfluous target on SHOOT/HOLD is ignored with warning, not marked invalid
    ok6, reason6, details6 = validate_action(
        state, ActionProposal(player_id="A1", action="SHOOT", target="PAINT")
    )
    assert ok6 is True
    assert reason6 is None
    assert "WARN" in details6
    remapped, rec = remap_invalid_action(
        state, ActionProposal(player_id="A1", action="SHOOT", target="PAINT")
    )
    assert rec is None
    assert remapped.target is None


def test_zone_target_movement_steps_toward_zone_within_limit():
    config = SimulationConfig()
    session = EngineSession(seed=10, config=config)
    state = session.state
    # Place A2 at (7, 9) (TOP) and have A2 CUT toward LEFT_CORNER (0, 8)
    state.players["A2"].pos = (7, 9)
    state.players["A2"].prev_pos = (7, 9)
    proposals = {
        "A1": ActionProposal(player_id="A1", action="DRIBBLE_MOVE", target="LEFT_WING"),
        "A2": ActionProposal(player_id="A2", action="CUT", target="LEFT_CORNER"),
        "A3": ActionProposal(player_id="A3", action="SPOT_UP", target="RIGHT_CORNER"),
        "B1": ActionProposal(player_id="B1", action="DEFEND", target="A1"),
        "B2": ActionProposal(player_id="B2", action="DEFEND", target="A2"),
        "B3": ActionProposal(player_id="B3", action="DEFEND", target="A3"),
    }
    payload = session.step(proposals)
    assert payload["new_violations"] == []
    # A2 moved 1 step toward LEFT_CORNER (0, 8) from (7, 9) -> (6, 9)
    assert state.players["A2"].pos == (6, 9)
    assert ZONES["LEFT_CORNER"] == (0, 8)


def test_format_legal_action_hints():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1), first_possession="A")
    assert format_legal_action_hint(state, "A1", "PASS") == "PASS (target: A2 | A3)"
    assert format_legal_action_hint(state, "A1", "DRIVE") == (
        "DRIVE (optional target: LEFT | RIGHT | MIDDLE | BASELINE)"
    )
    assert format_legal_action_hint(state, "A2", "CUT") == "CUT (optional target: zone)"
    assert format_legal_action_hint(state, "B1", "DENY") == "DENY (target: A1 | A2 | A3)"
    assert format_legal_action_hint(state, "A1", "SHOOT") == "SHOOT"


def test_first_possession_override_and_default():
    for team in ("A", "B"):
        assert EngineSession(seed=7, first_possession=team).state.offense == team
    default = create_initial_state(SimulationConfig(), GameRNG.from_seed(7))
    assert EngineSession(seed=7).state.offense == default.offense
