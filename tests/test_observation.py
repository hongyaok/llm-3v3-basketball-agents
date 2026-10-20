"""Unit tests for WS3 Observation builder, renderer, and PersonalMemory (P2)."""

from bball3x3.agents.context import (
    SimpleCoordinationView,
    StaticCoordinationView,
    build_initial_memory_entries,
)
from bball3x3.agents.observation import build_observation, render_observation
from bball3x3.config import SimulationConfig, load_initial_memory_config
from bball3x3.engine.actions import validate_action
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.rules import apply_missed_shot
from bball3x3.engine.session import EngineSession
from bball3x3.engine.state import create_initial_state
from bball3x3.memory.personal import PersonalMemory
from bball3x3.schemas.actions import ActionProposal
from bball3x3.schemas.agent import AgentOutput, CoordinationConfig
from bball3x3.schemas.memory import CSEntry, MemoryEntry
from bball3x3.schemas.messages import CaptainCall, Directive, Message


def test_observation_roles_and_flags():
    cfg = SimulationConfig()
    state = create_initial_state(cfg, GameRNG.from_seed(5), first_possession="A")

    # 1. Ball handler (A1)
    obs_bh = build_observation(state, "A1")
    assert obs_bh.role == "BALL_HANDLER"
    text_bh = render_observation(obs_bh)
    assert "Role: BALL_HANDLER" in text_bh
    assert "[PREVIOUS CAPTAIN CALL]\nnone" in text_bh
    assert "[PREVIOUS TEAMMATE MESSAGES]\nnone" in text_bh
    assert "[PERSONAL MEMORY]\nnone" in text_bh
    assert "[SHARED TEAM MEMORY]\nnone" in text_bh
    assert "[COUNTER-STRATEGY TABLE]\nempty" in text_bh

    # 2. Off-ball (A2)
    obs_ob = build_observation(state, "A2")
    assert obs_ob.role == "OFF_BALL"
    assert "Role: OFF_BALL" in render_observation(obs_ob)

    # 3. Defender (B1)
    obs_def = build_observation(state, "B1")
    assert obs_def.role == "DEFENSE"
    assert "Role: DEFENSE" in render_observation(obs_def)

    # 4. Needs clear, OT, shot clock low
    state.needs_clear = True
    state.shot_clock_s = 2.0
    state.phase = "OT"
    obs_flags = build_observation(state, "A1")
    assert obs_flags.flags == ["SHOT_CLOCK_LOW", "NEEDS_CLEAR", "OVERTIME"]
    assert "CLEAR" in obs_flags.legal_actions
    assert "SHOOT" not in obs_flags.legal_actions
    text_flags = render_observation(obs_flags)
    assert "Flags: SHOT_CLOCK_LOW, NEEDS_CLEAR, OVERTIME" in text_flags

    # 5. Loose ball (rebound phase: D5 all 6 players see role REBOUND)
    apply_missed_shot(state)
    for pid in state.players:
        obs_reb = build_observation(state, pid)
        assert obs_reb.role == "REBOUND"
        assert set(obs_reb.legal_actions) == {
            "BOX_OUT",
            "CRASH_BOARDS",
            "GET_BACK",
            "HOLD",
            "MOVE",
        }


def test_coordination_flags_and_no_opponent_leakage():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(5), first_possession="A")
    cap_call = CaptainCall(
        maintain=False,
        tactic=Message(
            sender="A1",
            is_captain_channel=True,
            kind="tactic",
            text="spread the floor",
            cs="01",
        ),
        directives=[
            Message(
                sender="A1",
                is_captain_channel=True,
                kind="action",
                text="cut to paint",
                directive=Directive(to="A2", act="CUT", target="PAINT"),
            )
        ],
    )
    coord = StaticCoordinationView(
        captain_calls={"A": cap_call},
        inboxes={
            "A2": [
                Message(sender="A3", kind="info", text="I am open on the wing"),
                Message(
                    sender="A1",
                    is_captain_channel=True,
                    kind="action",
                    text="cut to paint",
                    directive=Directive(to="A2", act="CUT", target="PAINT"),
                ),
                # Attempted opponent message injection: must NEVER appear
                Message(sender="B1", kind="info", text="secret opponent message"),
            ]
        },
        shared_memories={
            "A": [
                MemoryEntry(
                    id="M01",
                    opponent="B1",
                    category="defensive_tendency",
                    tendency="leaves passing lanes open",
                    confidence=2,
                )
            ]
        },
        cs_tables={
            "A": [
                CSEntry(
                    key="01",
                    side="offense",
                    opponent_strategy="B switches screens",
                    counter_strategy="slip screen early",
                    created_by="A1",
                )
            ]
        },
    )

    # Full coordination (Team A)
    obs_a = build_observation(
        state,
        "A2",
        coordination=coord,
        flags=CoordinationConfig(comms=True, captain=True, memory_write=True),
    )
    txt_a = render_observation(obs_a)
    assert "secret opponent message" not in txt_a
    assert "<A3>I am open on the wing</A3>" in txt_a
    assert "<A1><c>[action to=A2 act=CUT target=PAINT] cut to paint [/action]</c></A1>" in txt_a
    assert "M01: B1 (defensive_tendency) — leaves passing lanes open (confidence: 2)" in txt_a
    assert '01 [offense]: vs "B switches screens" -> "slip screen early"' in txt_a

    # Team B (comms=False, captain=True): non-captain message hidden, captain directive survives!
    obs_b = build_observation(
        state,
        "A2",
        coordination=coord,
        flags=CoordinationConfig(comms=False, captain=True, memory_write=True),
    )
    txt_b = render_observation(obs_b)
    assert "<A3>I am open on the wing</A3>" not in txt_b
    assert "<A1><c>[action to=A2 act=CUT target=PAINT] cut to paint [/action]</c></A1>" in txt_b

    # Team C (comms=True, captain=False): captain call rendered as none
    obs_c = build_observation(
        state,
        "A2",
        coordination=coord,
        flags=CoordinationConfig(comms=True, captain=False, memory_write=True),
    )
    txt_c = render_observation(obs_c)
    assert "[PREVIOUS CAPTAIN CALL]\nnone" in txt_c


def test_target_hints_align_with_validate_action():
    state = create_initial_state(SimulationConfig(), GameRNG.from_seed(5), first_possession="A")
    for pid in state.players:
        obs = build_observation(state, pid)
        for act, hint in zip(obs.legal_actions, obs.legal_action_hints):
            if "(target:" in hint:
                inner = hint.split("(target:")[1].rstrip(")").strip()
                first_opt = inner.split("|")[0].strip()
                target = "TOP" if first_opt == "zone" else first_opt
                ok, reason, _ = validate_action(
                    state, ActionProposal(player_id=pid, action=act, target=target)
                )
                assert ok is True, f"{pid} {act} target={target} failed: {reason}"
            else:
                ok, reason, _ = validate_action(
                    state, ActionProposal(player_id=pid, action=act, target=None)
                )
                assert ok is True, f"{pid} {act} target=None failed: {reason}"


def test_personal_memory_and_simple_coordination_view():
    session = EngineSession(seed=7)
    pm = PersonalMemory("A1", maxlen=8)
    for _ in range(12):
        proposals = {}
        for pid in session.state.players:
            is_holder = (
                session.state.players[pid].has_ball
                and session.state.ball.status == "HELD"
            )
            target = (
                "A2"
                if pid == "A1"
                else ("A1" if pid[:1] == "A" else ("B2" if pid == "B1" else "B1"))
            )
            proposals[pid] = ActionProposal(
                player_id=pid,
                action="PASS" if is_holder else "HOLD",
                target=target,
            )
        prev = session.state.model_copy(deep=True)
        payload = session.step(proposals)
        pm.update(prev, session.state, payload)

    assert 1 <= len(pm.lines()) <= 8
    assert all(line.startswith("E") for line in pm.lines())

    init_mem = build_initial_memory_entries(load_initial_memory_config())
    assert len(init_mem["A"]) == 2
    assert init_mem["A"][0].id == "M01"
    assert init_mem["A"][0].opponent == "B1"

    simple = SimpleCoordinationView(initial_memory=init_mem)
    kept = {
        "A1": AgentOutput(
            action="PASS",
            target="A2",
            messages=[Message(sender="A1", kind="info", text="watch the clock")],
        )
    }
    simple.record_event(1, kept, {"A": CoordinationConfig(), "B": CoordinationConfig()})
    assert len(simple.inbox("A", "A2", 2)) == 1
    assert simple.inbox("B", "B1", 2) == []
