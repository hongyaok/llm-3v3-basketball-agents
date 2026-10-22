"""Engine-owned objective rules cannot be overwritten by referee output."""

import pytest

from bball3x3.agents.base import BasePlayer
from bball3x3.analysis.log_reader import read_game_log
from bball3x3.analysis.metrics import compute_game_metrics
from bball3x3.analysis.possessions import validate_possessions
from bball3x3.config import SimulationConfig
from bball3x3.engine.loop import play_heuristic_game
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.state import create_initial_state
from bball3x3.referee import RuleBasedReferee
from bball3x3.runner.game import run_logged_game
from bball3x3.schemas.actions import ActionProposal
from bball3x3.schemas.referee import RefereeDecision


class NoCallReferee(RuleBasedReferee):
    def judge(self, referee_state):
        return RefereeDecision()


class InvalidObjectiveReferee(NoCallReferee):
    def __init__(self, as_mapping):
        super().__init__()
        self.as_mapping = as_mapping
        self.proposed = False

    def judge(self, referee_state):
        if not self.proposed:
            self.proposed = True
            # A future backend can construct a decision before schema
            # validation. The engine must still reject the objective claim.
            raw = {
                "call": "VIOLATION", "offender": f"{referee_state.possession}1",
                "violation_type": "SHOT_CLOCK",
            }
            return raw if self.as_mapping else RefereeDecision.model_construct(**raw)
        return RefereeDecision()


class FoulOnObjectiveEvent(NoCallReferee):
    def judge(self, referee_state):
        if referee_state.current_event["event_type"] == "SHOT_CLOCK":
            other = "B" if referee_state.possession == "A" else "A"
            return RefereeDecision(
                call="FOUL", offender=f"{other}1",
                fouled_player=f"{referee_state.possession}1",
                foul_type="DEFENSIVE_FOUL",
            )
        return RefereeDecision()


class HoldPlayer(BasePlayer):
    def decide(self, state, **kwargs):
        return ActionProposal(player_id=self.player_id, action="HOLD")


@pytest.mark.parametrize("as_mapping", [False, True])
def test_rejected_objective_proposal_is_logged_without_changing_game(
    tmp_path, as_mapping,
):
    invalid_path = tmp_path / "invalid.jsonl"
    baseline_path = tmp_path / "baseline.jsonl"
    run_logged_game(
        seed=17, path=invalid_path,
        referee=InvalidObjectiveReferee(as_mapping), max_events=80,
    )
    run_logged_game(
        seed=17, path=baseline_path, referee=NoCallReferee(), max_events=80,
    )
    invalid = read_game_log(invalid_path)
    baseline = read_game_log(baseline_path)
    validate_possessions(invalid)
    validate_possessions(baseline)

    rejected = invalid.by_type["referee"][0]
    assert rejected.decision.call == "NONE"
    assert rejected.rejection_reason == "OBJECTIVE_VIOLATION"
    assert rejected.rejected_output["violation_type"] == "SHOT_CLOCK"
    assert rejected.rejected_output["call"] == "VIOLATION"
    assert compute_game_metrics(invalid).referee_call_rate.numerator == 0
    assert invalid.by_type["state"][-1].state == baseline.by_type["state"][-1].state
    assert not invalid.by_type.get("invariant_violation")


def test_foul_proposed_on_engine_shot_clock_event_is_rejected():
    config = SimulationConfig()
    start = create_initial_state(config, GameRNG.from_seed(3), first_possession="A")
    start.shot_clock_s = 0.5
    payloads = []
    play_heuristic_game(
        seed=3, config=config, max_events=1, start_state=start,
        agent_factory=HoldPlayer, referee=FoulOnObjectiveEvent(),
        on_event=lambda payload: payloads.append(payload) if payload["type"] == "event" else None,
    )

    event = payloads[0]
    assert event["referee_decision"].call == "NONE"
    assert event["referee_rejection_reason"] == "OBJECTIVE_EVENT"
    assert event["referee_rejected_output"]["call"] == "FOUL"
    assert event["event"]["possession_reason"] == "SHOT_CLOCK"
    assert event["state"].team_fouls == {"A": 0, "B": 0}
    assert not event["new_violations"]
