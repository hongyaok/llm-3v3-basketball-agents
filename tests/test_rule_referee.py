"""Phase A referee decisions from structured event and contact evidence."""

import pytest

from bball3x3.config import SimulationConfig
from bball3x3.engine.contact import build_referee_state, detect_contact
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.state import create_initial_state
from bball3x3.referee import RuleBasedReferee
from bball3x3.schemas.referee import ContactEvent, RefereeState
from bball3x3.schemas.state import BallState, PlayerState


def _state(
    contact_type: str | None = None,
    players_involved: list[str] | None = None,
    *,
    event: dict | None = None,
    details: dict | None = None,
    ball_status: str = "HELD",
) -> RefereeState:
    players = {
        "A1": PlayerState(id="A1", team="A", pos=(5, 5), prev_pos=(5, 5), has_ball=True),
        "A2": PlayerState(id="A2", team="A", pos=(4, 5), prev_pos=(4, 5)),
        "B1": PlayerState(id="B1", team="B", pos=(6, 5), prev_pos=(6, 5)),
        "B2": PlayerState(id="B2", team="B", pos=(7, 5), prev_pos=(7, 5)),
    }
    return RefereeState(
        event_idx=1, possession="A", ball_handler="A1", players=players,
        ball=BallState(status=ball_status, pos=(5, 5), holder="A1"),
        current_event=event or {},
        contact_event=ContactEvent(
            contact_detected=contact_type is not None,
            contact_type=contact_type,
            players_involved=players_involved or [],
            details=details or {},
        ),
    )


def _certain_referee() -> RuleBasedReferee:
    return RuleBasedReferee(foul_probabilities={
        "BODY_CONTACT_DRIVE": 1.0, "REACH": 1.0,
        "SCREEN_CONTACT": 1.0, "LOOSE_BALL": 1.0,
    })


@pytest.mark.parametrize(
    ("state", "call", "foul_type", "offender", "fouled"),
    [
        (_state("BODY_CONTACT_DRIVE", ["A1", "B1"]),
         "FOUL", "DEFENSIVE_FOUL", "B1", "A1"),
        (_state("BODY_CONTACT_DRIVE", ["A1", "B1"],
                event={"offensive_contact": True}),
         "FOUL", "OFFENSIVE_FOUL", "A1", "B1"),
        (_state("BODY_CONTACT_DRIVE", ["A1", "B1"],
                event={"was_shooting": True}),
         "FOUL", "SHOOTING_FOUL", "B1", "A1"),
        (_state("REACH", ["B1", "A1"]),
         "FOUL", "DEFENSIVE_FOUL", "B1", "A1"),
        (_state("SCREEN_CONTACT", ["A2"], details={"fouled_player": "B2"}),
         "FOUL", "OFFENSIVE_FOUL", "A2", "B2"),
        (_state("LOOSE_BALL", ["A2", "B2"],
                details={"offender": "A2", "fouled_player": "B2"}),
         "FOUL", "LOOSE_BALL_FOUL", "A2", "B2"),
        (_state("REACH", ["B1", "A1"], event={"unsportsmanlike_contact": True}),
         "FOUL", "UNSPORTSMANLIKE", "B1", "A1"),
        (_state(event={"technical_conduct": True, "offender": "B1"}),
         "FOUL", "TECHNICAL", "B1", None),
    ],
)
def test_supported_fouls_have_real_participants(state, call, foul_type, offender, fouled):
    before = state.model_dump()
    decision = _certain_referee().judge(state)
    assert (decision.call, decision.foul_type, decision.offender,
            decision.fouled_player) == (call, foul_type, offender, fouled)
    assert state.model_dump() == before


@pytest.mark.parametrize("violation", ["GOALTENDING", "BASKET_INTERFERENCE", "STALLING"])
def test_explicit_judgement_violation(violation):
    decision = RuleBasedReferee().judge(
        _state(event={"judgement_violation": violation, "offender": "B1"})
    )
    assert decision.call == "VIOLATION"
    assert decision.violation_type == violation
    assert decision.offender == "B1"


@pytest.mark.parametrize(
    "state",
    [
        _state(),
        _state("SCREEN_CONTACT", ["A2"]),  # Detector has no screen victim yet.
        _state("LOOSE_BALL", ["A2", "B2"]),  # No evidence of who fouled whom.
        _state("REACH", ["B1", "B2"]),  # A teammate cannot foul a teammate here.
        _state("REACH", ["unknown", "A1"]),
        _state(event={"technical_conduct": True, "offender": "unknown"}),
        _state(event={"judgement_violation": "SHOT_CLOCK", "offender": "B1"}),
        _state("REACH", ["B1", "A1"], event={"event_type": "SHOT_CLOCK"}),
    ],
)
def test_no_call_without_sufficient_judgement_evidence(state):
    assert RuleBasedReferee().judge(state).call == "NONE"


def test_referee_uses_independent_seeded_randomness():
    state = _state("REACH", ["B1", "A1"])
    first = RuleBasedReferee(seed=43)
    second = RuleBasedReferee(seed=43)
    first.judge(_state())  # No-contact states must not use a random draw.
    calls = [first.judge(state).call for _ in range(20)]
    assert calls == [second.judge(state).call for _ in range(20)]
    assert "FOUL" in calls and "NONE" in calls


def test_judges_actual_drive_contact_from_engine_detector():
    config = SimulationConfig(contact={"drive_contest_prob": 1.0})
    state = create_initial_state(config, GameRNG.from_seed(8), first_possession="A")
    contact, _ = detect_contact(
        state=state, actions={"A1": "DRIVE", "B1": "DEFEND"},
        ball_handler_id="A1", primary_defender_id="B1",
        rng=GameRNG.from_seed(8), config=config,
    )
    assert contact.contact_type == "BODY_CONTACT_DRIVE"
    decision = _certain_referee().judge(build_referee_state(
        state=state, contact=contact, current_event={"event_type": "DRIVE"},
    ))
    assert (decision.call, decision.offender, decision.fouled_player) == (
        "FOUL", "B1", "A1",
    )


def test_malformed_event_markers_do_not_crash_the_referee():
    state = _state(event={"event_type": [], "judgement_violation": [], "offender": "B1"})
    assert RuleBasedReferee().judge(state).call == "NONE"


@pytest.mark.parametrize("probability", [-0.1, 1.1, float("nan"), True])
def test_invalid_probability_is_rejected(probability):
    with pytest.raises(ValueError, match="Invalid foul probability"):
        RuleBasedReferee(foul_probabilities={"REACH": probability})
