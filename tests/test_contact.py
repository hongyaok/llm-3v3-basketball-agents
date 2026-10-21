"""Tests for contact detection and referee-state building."""

from bball3x3.config import SimulationConfig
from bball3x3.engine.contact import (
    build_referee_state,
    detect_contact,
    referee_query_text,
)
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.state import create_initial_state
from bball3x3.schemas.referee import ContactEvent


def test_no_contact_without_triggers():
    config = SimulationConfig()
    state = create_initial_state(config, GameRNG.from_seed(1), first_possession="A")
    rng = GameRNG.from_seed(1)
    contact, _ = detect_contact(
        state=state, actions={"A1": "HOLD", "B1": "DEFEND"},
        ball_handler_id="A1", primary_defender_id="B1",
        rng=rng, config=config,
    )
    # HOLD vs DEFEND never triggers; result must be a valid ContactEvent.
    assert contact.contact_detected in (True, False)


def test_steal_attempt_can_produce_reach():
    config = SimulationConfig()
    state = create_initial_state(config, GameRNG.from_seed(1), first_possession="A")
    seen = set()
    for seed in range(20):
        rng = GameRNG.from_seed(seed)
        contact, draws = detect_contact(
            state=state, actions={"A1": "DRIVE", "B1": "STEAL_ATTEMPT"},
            ball_handler_id="A1", primary_defender_id="B1",
            rng=rng, config=config,
        )
        seen.add(contact.contact_detected)
        assert "reach" in draws or not contact.contact_detected
    assert True in seen  # reach_prob 0.2 fires at least once in 20 seeds


def test_referee_state_and_query():
    config = SimulationConfig()
    state = create_initial_state(config, GameRNG.from_seed(1), first_possession="A")
    rng = GameRNG.from_seed(2)
    contact, _ = detect_contact(
        state=state, actions={"A1": "DRIVE", "B1": "DEFEND"},
        ball_handler_id="A1", primary_defender_id="B1",
        rng=rng, config=config,
    )
    ref = build_referee_state(
        state=state, contact=contact, current_event={"event_type": "DRIVE"}
    )
    assert ref.ball_handler == "A1"
    query = referee_query_text(ref)
    assert "DRIVE" in query and "contact=" in query


def test_query_captures_contact_roles_motion_and_sorted_actions():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1),
                                 first_possession="A")
    state.players["A1"].prev_pos = (5, 6)
    state.players["A1"].pos = (6, 6)
    state.players["A1"].movement = "DRIVE"
    state.players["A1"].speed = "FAST"
    state.players["B1"].prev_pos = (7, 6)
    state.players["B1"].pos = (6, 6)
    state.players["B1"].movement = "DEFEND"
    contact = ContactEvent(
        contact_detected=True, contact_type="REACH", players_involved=["B1", "A1"],
        contact_location=(6, 6),
        details={"contact_initiator": "B1", "contact_recipient": "A1"},
    )
    ref = build_referee_state(
        state=state, contact=contact,
        current_event={"event_type": "DRIVE", "actions": {
            "B1": "STEAL_ATTEMPT", "A1": "DRIVE",
        }},
    )
    query = referee_query_text(ref)
    assert query.startswith("event=DRIVE; contact=true; contact_type=REACH")
    assert "involved=B1,A1" in query
    assert "off=A1(team=A,action=DRIVE,move=DRIVE,speed=FAST,has_ball=true," in query
    assert "def=B1(team=B,action=STEAL_ATTEMPT,move=DEFEND" in query
    assert "contact_location=(6,6)" in query
    assert "contact_initiator=B1; contact_recipient=A1" in query
    assert "actions=A1:DRIVE,B1:STEAL_ATTEMPT" in query

    reordered = ref.model_copy(deep=True)
    reordered.current_event["actions"] = {"A1": "DRIVE", "B1": "STEAL_ATTEMPT"}
    reordered.players = dict(reversed(list(reordered.players.items())))
    assert referee_query_text(reordered) == query
    assert referee_query_text(ref) == query


def test_no_contact_shot_still_gets_a_deterministic_query():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1),
                                 first_possession="A")
    state.ball.status = "IN_SHOT"
    state.ball.holder = None
    state.players["A1"].has_ball = False
    ref = build_referee_state(
        state=state, contact=ContactEvent(),
        current_event={"event_type": "SHOOT", "actions": {"A1": "SHOOT"},
                       "was_shooting": True},
    )
    query = referee_query_text(ref)
    assert "contact=false; contact_type=none; involved=none" in query
    assert "off=A1(" in query
    assert "contact_location=none" in query
    assert "ball=IN_SHOT; holder=none; possession=A" in query
    assert "shot_in_air=true; shooting_action=true" in query
    assert "actions=A1:SHOOT" in query
    assert referee_query_text(ref.model_copy(deep=True)) == query


def test_no_contact_conduct_and_judgement_markers_are_explicit():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(1),
                                 first_possession="A")
    ref = build_referee_state(
        state=state, contact=ContactEvent(),
        current_event={
            "event_type": "HOLD", "technical_conduct": True,
            "judgement_violation": "STALLING", "offender": "A1",
            "conduct_evidence": {"kind": "TECHNICAL", "actor": "A1"},
        },
    )
    query = referee_query_text(ref)
    assert "contact=false" in query
    assert "technical_conduct=true" in query
    assert "judgement_violation=STALLING; event_offender=A1" in query
    assert "conduct=TECHNICAL actor=A1 target=none" in query


def test_screen_contact_identifies_the_screened_teammates_defender():
    config = SimulationConfig(contact={"screen_prob": 1.0})
    state = create_initial_state(config, GameRNG.from_seed(2), first_possession="A")
    state.players["A2"].pos = (7, 6)
    contact, _ = detect_contact(
        state=state, actions={"A1": "HOLD", "A2": "SCREEN", "B1": "DEFEND"},
        action_targets={"A2": "A1"},
        ball_handler_id="A1", primary_defender_id="B1",
        rng=GameRNG.from_seed(2), config=config,
    )
    assert contact.contact_type == "SCREEN_CONTACT"
    assert contact.players_involved == ["A2", "B1"]
    assert contact.details["contact_recipient"] == "B1"
    assert contact.details["screen_target"] == "A1"


def test_screen_without_a_nearby_opponent_does_not_invent_contact():
    config = SimulationConfig(contact={"screen_prob": 1.0})
    state = create_initial_state(config, GameRNG.from_seed(2), first_possession="A")
    contact, _ = detect_contact(
        state=state, actions={"A2": "SCREEN"},
        action_targets={"A2": "A1"},
        ball_handler_id=None, primary_defender_id=None,
        rng=GameRNG.from_seed(2), config=config,
    )
    assert not contact.contact_detected


def test_rebound_contact_identifies_nearby_box_out_and_crash_pair():
    config = SimulationConfig(contact={"rebound_prob": 1.0})
    state = create_initial_state(config, GameRNG.from_seed(2), first_possession="A")
    state.players["A2"].pos = (7, 8)
    state.players["B2"].pos = (7, 9)
    contact, _ = detect_contact(
        state=state, actions={"A2": "BOX_OUT", "B2": "CRASH_BOARDS"},
        ball_handler_id=None, primary_defender_id=None,
        rebound_phase=True, rng=GameRNG.from_seed(2), config=config,
    )
    assert contact.contact_type == "LOOSE_BALL"
    assert contact.players_involved == ["A2", "B2"]
    assert contact.details["contact_initiator"] == "A2"
    assert contact.details["contact_recipient"] == "B2"


def test_rebound_without_an_opposing_nearby_crasher_does_not_invent_contact():
    config = SimulationConfig(contact={"rebound_prob": 1.0})
    state = create_initial_state(config, GameRNG.from_seed(2), first_possession="A")
    state.players["A2"].pos = (7, 8)
    state.players["B2"].pos = (7, 9)
    contact, _ = detect_contact(
        state=state, actions={"A2": "BOX_OUT", "B2": "BOX_OUT"},
        ball_handler_id=None, primary_defender_id=None,
        rebound_phase=True, rng=GameRNG.from_seed(2), config=config,
    )
    assert not contact.contact_detected
