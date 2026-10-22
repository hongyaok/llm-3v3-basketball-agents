"""The live referee call must affect the engine and the logged game equally."""

import pytest

from bball3x3.analysis.log_reader import read_game_log
from bball3x3.analysis.possessions import validate_possessions
from bball3x3.config import SimulationConfig
from bball3x3.referee import RuleBasedReferee
from bball3x3.runner.game import run_logged_game
from bball3x3.schemas.referee import RefereeDecision


class RecordingReferee(RuleBasedReferee):
    def __init__(self):
        super().__init__(
            seed=17,
            foul_probabilities={"BODY_CONTACT_DRIVE": 1.0, "REACH": 1.0},
        )
        self.seen_event_indices = []

    def judge(self, referee_state):
        self.seen_event_indices.append(referee_state.event_idx)
        return super().judge(referee_state)


class OneReboundCall(RuleBasedReferee):
    def __init__(self, call):
        super().__init__(seed=17, foul_probabilities={
            "BODY_CONTACT_DRIVE": 0.0, "REACH": 0.0,
            "SCREEN_CONTACT": 0.0, "LOOSE_BALL": 0.0,
        })
        self.call = call
        self.called = False

    def judge(self, referee_state):
        if referee_state.current_event["event_type"] == "REBOUND" and not self.called:
            self.called = True
            winner_team = referee_state.possession
            other = "B" if winner_team == "A" else "A"
            if self.call in {"FOUL", "FOUL_WINNER"}:
                offender = other if self.call == "FOUL" else winner_team
                fouled = winner_team if self.call == "FOUL" else other
                return RefereeDecision(
                    call="FOUL", offender=f"{offender}1",
                    fouled_player=f"{fouled}1", foul_type="LOOSE_BALL_FOUL",
                )
            return RefereeDecision(
                call="VIOLATION", offender=f"{winner_team}1",
                violation_type="STALLING",
            )
        return RefereeDecision()


class OneShootingFoul(RuleBasedReferee):
    def __init__(self):
        super().__init__(seed=17)
        self.called = False

    def judge(self, referee_state):
        event = referee_state.current_event
        if (event["event_type"] == "SHOOT" and referee_state.ball.status == "LOOSE"
                and not self.called):
            self.called = True
            shooter = next(pid for pid, action in event["actions"].items() if action == "SHOOT")
            other = "B" if shooter.startswith("A") else "A"
            return RefereeDecision(
                call="FOUL", offender=f"{other}1",
                fouled_player=shooter, foul_type="SHOOTING_FOUL",
            )
        return RefereeDecision()


def test_rule_referee_calls_are_applied_and_logged(tmp_path):
    # Force enough contact to exercise bonus free throws in a short game.
    config = SimulationConfig(contact={"drive_contest_prob": 1.0, "reach_prob": 1.0})
    referee = RecordingReferee()
    path = tmp_path / "game.jsonl"

    result = run_logged_game(
        seed=17, path=path, config=config, referee=referee, max_events=1000,
    )
    log = read_game_log(path)
    validate_possessions(log)

    assert result["game_complete"]
    calls = log.by_type["referee"]
    states = log.by_type["state"]
    assert len(calls) == len(states) == result["events"]
    assert referee.seen_event_indices == list(range(1, result["events"] + 1))
    fouls = [record.decision for record in calls if record.decision.call == "FOUL"]
    assert fouls
    assert all(record.query for record in calls)
    for team in ("A", "B"):
        assert states[-1].state.team_fouls[team] == sum(
            decision.offender.startswith(team) for decision in fouls
        )

    free_throw_points = sum(
        score.points
        for resolution in log.by_type["resolution"]
        for score in resolution.scoring_events
        if score.source == "FREE_THROW"
    )
    assert free_throw_points > 0
    assert not log.by_type.get("invariant_violation")


@pytest.mark.parametrize("call", ["FOUL", "FOUL_WINNER", "VIOLATION"])
def test_rebound_referee_call_changes_state_and_matches_log(tmp_path, call):
    referee = OneReboundCall(call)
    path = tmp_path / f"rebound_{call}.jsonl"
    run_logged_game(seed=17, path=path, referee=referee, max_events=1000)
    log = read_game_log(path)
    validate_possessions(log)

    assert referee.called
    logged_call = "FOUL" if call == "FOUL_WINNER" else call
    record = next(r for r in log.by_type["referee"] if r.decision.call == logged_call)
    state = next(r.state for r in log.by_type["state"] if r.event_idx == record.event_idx)
    resolution = next(
        r for r in log.by_type["resolution"] if r.event_idx == record.event_idx
    )
    offender_team = record.decision.offender[0]
    if logged_call == "FOUL":
        assert state.team_fouls[offender_team] == 1
        assert state.offense != offender_team
    else:
        assert state.offense != offender_team
        assert state.team_fouls == {"A": 0, "B": 0}
    assert bool(resolution.possession_changes) == (
        resolution.possession_before.team != state.offense
    )
    assert not log.by_type.get("invariant_violation")


def test_free_throw_does_not_turn_missed_field_goal_into_make(tmp_path):
    referee = OneShootingFoul()
    path = tmp_path / "shooting_foul.jsonl"
    run_logged_game(seed=17, path=path, referee=referee, max_events=1000)
    log = read_game_log(path)
    validate_possessions(log)

    assert referee.called
    call = next(
        r for r in log.by_type["referee"]
        if r.decision.foul_type == "SHOOTING_FOUL"
    )
    resolution = next(
        r for r in log.by_type["resolution"] if r.event_idx == call.event_idx
    )
    assert resolution.shots[0].made is False
    assert all(score.source == "FREE_THROW" for score in resolution.scoring_events)
    assert not log.by_type.get("invariant_violation")


def test_live_screen_and_loose_ball_contacts_produce_logged_calls(tmp_path):
    config = SimulationConfig(contact={
        "drive_contest_prob": 0.0, "reach_prob": 0.0,
        "screen_prob": 1.0, "rebound_prob": 1.0,
    })
    referee = RuleBasedReferee(seed=0, foul_probabilities={
        "BODY_CONTACT_DRIVE": 0.0, "REACH": 0.0,
        "SCREEN_CONTACT": 1.0, "LOOSE_BALL": 1.0,
    })
    path = tmp_path / "live_contacts.jsonl"
    result = run_logged_game(
        seed=0, path=path, config=config, referee=referee, max_events=1000,
    )
    log = read_game_log(path)
    validate_possessions(log)

    assert result["game_complete"]
    calls = [r.decision for r in log.by_type["referee"] if r.decision.call == "FOUL"]
    assert {"OFFENSIVE_FOUL", "LOOSE_BALL_FOUL"} <= {
        decision.foul_type for decision in calls
    }
    for team in ("A", "B"):
        assert log.by_type["state"][-1].state.team_fouls[team] == sum(
            decision.offender.startswith(team) for decision in calls
        )
    assert not log.by_type.get("invariant_violation")
