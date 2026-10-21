"""Explicit special conduct reaches the referee only with matching evidence."""

from bball3x3.agents.base import BasePlayer
from bball3x3.analysis.log_reader import read_game_log
from bball3x3.config import SimulationConfig
from bball3x3.engine.conduct import collect_conduct_evidence
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.state import create_initial_state
from bball3x3.referee import RuleBasedReferee
from bball3x3.runner.game import run_logged_game
from bball3x3.schemas.actions import ActionProposal
from bball3x3.schemas.referee import ContactEvent


class TechnicalPlayer(BasePlayer):
    def decide(self, state, **kwargs):
        conduct = "TECHNICAL" if self.player_id == "A1" else None
        return ActionProposal(player_id=self.player_id, action="HOLD", conduct=conduct)


class UnsportsmanlikePlayer(BasePlayer):
    def decide(self, state, **kwargs):
        holder = state.ball.holder
        if state.matchups.get(self.player_id) == holder:
            return ActionProposal(
                player_id=self.player_id, action="STEAL_ATTEMPT",
                conduct="UNSPORTSMANLIKE", conduct_target=holder,
            )
        return ActionProposal(player_id=self.player_id, action="HOLD")


def test_technical_signal_is_applied_and_preserved_in_jsonl(tmp_path):
    path = tmp_path / "technical.jsonl"
    run_logged_game(path=path, seed=17, max_events=1, agent_factory=TechnicalPlayer)
    log = read_game_log(path)

    referee = log.by_type["referee"][0]
    resolution = log.by_type["resolution"][0]
    decision = next(r for r in log.by_type["decision"] if r.player == "A1")
    assert referee.decision.foul_type == "TECHNICAL"
    assert referee.decision.offender == "A1"
    assert "conduct=TECHNICAL actor=A1" in referee.query
    assert resolution.outcomes["conduct_evidence"] == {
        "kind": "TECHNICAL", "actor": "A1", "action": "HOLD",
        "source": "ACTION_PROPOSAL",
    }
    assert decision.parsed_output.conduct == "TECHNICAL"
    assert '"conduct":"TECHNICAL"' in decision.raw_output
    assert log.by_type["state"][0].state.team_fouls["A"] == 1


def test_unsportsmanlike_signal_requires_resolved_contact_and_is_logged(tmp_path):
    path = tmp_path / "unsportsmanlike.jsonl"
    config = SimulationConfig(contact={"reach_prob": 1.0})
    referee = RuleBasedReferee(seed=17, foul_probabilities={"REACH": 1.0})
    run_logged_game(
        path=path, seed=17, max_events=1, config=config,
        agent_factory=UnsportsmanlikePlayer, referee=referee,
    )
    log = read_game_log(path)
    call = log.by_type["referee"][0]
    evidence = log.by_type["resolution"][0].outcomes["conduct_evidence"]
    assert call.decision.foul_type == "UNSPORTSMANLIKE"
    assert call.decision.offender == evidence["actor"]
    assert call.decision.fouled_player == evidence["target"]
    assert evidence["contact_type"] == "REACH"
    assert log.by_type["state"][0].state.team_fouls[evidence["actor"][0]] == 1


def test_unmatched_unsportsmanlike_and_remapped_action_supply_no_evidence():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(17))
    offender = next(pid for pid, p in state.players.items() if p.team != state.offense)
    recipient = next(pid for pid, p in state.players.items() if p.team == state.offense)
    proposal = ActionProposal(
        player_id=offender, action="STEAL_ATTEMPT",
        conduct="UNSPORTSMANLIKE", conduct_target=recipient,
    )
    assert collect_conduct_evidence(state, {offender: proposal}, ContactEvent()) == {}
    contact = ContactEvent(
        contact_detected=True, contact_type="REACH",
        players_involved=[offender, recipient],
    )
    wrong_target = proposal.model_copy(update={"conduct_target": offender})
    assert collect_conduct_evidence(state, {offender: wrong_target}, contact) == {}

    from bball3x3.engine.actions import remap_invalid_action

    invalid = proposal.model_copy(update={"action": "NO_SUCH_ACTION"})
    legalized, remap = remap_invalid_action(state, invalid)
    assert remap is not None
    assert legalized.conduct is None
    assert collect_conduct_evidence(state, {offender: legalized}, contact) == {}
