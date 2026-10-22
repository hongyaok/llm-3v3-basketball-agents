"""Shared-memory visibility, rejection, and ablation integration."""

from bball3x3.agents.context import SimpleCoordinationView
from bball3x3.schemas.agent import AgentOutput, CoordinationConfig
from bball3x3.schemas.memory import MemoryEntry, MemoryProposal


def initial_entry():
    return MemoryEntry(
        id="M01",
        opponent="B1",
        category="offensive_tendency",
        tendency="Often drives left",
    )


def submit(view, event_idx, tendency, *, flags=None, opponent="B1"):
    return view.record_event(
        event_idx,
        {
            "A1": AgentOutput(
                action="HOLD",
                memory_update=MemoryProposal(
                    opponent=opponent,
                    category="offensive_tendency",
                    tendency=tendency,
                ),
            )
        },
        {"A": flags if flags is not None else CoordinationConfig()},
    )


def test_write_is_visible_only_from_next_event():
    view = SimpleCoordinationView()
    writes, _ = submit(view, 1, "Often drives left")

    assert writes[0]["accepted"]
    assert writes[0]["visible_at"] == 2
    assert view.shared_memory("A", 1) == []
    assert view.shared_memory("A", 2)[0].id == "M01"
    assert view.shared_memory("B", 2) == []


def test_merge_preserves_historical_memory():
    view = SimpleCoordinationView(
        initial_memory={"A": [initial_entry()]}
    )
    submit(view, 1, "Often drives left")

    assert view.shared_memory("A", 1)[0].confidence == 1
    assert view.shared_memory("A", 2)[0].confidence == 2

    visible = view.shared_memory("A", 2)
    visible[0].confidence = 999
    assert view.shared_memory("A", 2)[0].confidence == 2


def test_memory_write_off_preserves_initial_memory():
    view = SimpleCoordinationView(
        initial_memory={"A": [initial_entry()]}
    )
    writes, cs_writes = submit(
        view,
        1,
        "Usually shoots from outside",
        flags=CoordinationConfig(memory_write=False),
    )

    assert writes == []
    assert cs_writes == []
    entries = view.shared_memory("A", 2)
    assert len(entries) == 1
    assert entries[0].tendency == "Often drives left"


def test_invalid_opponent_is_rejected_without_crashing():
    view = SimpleCoordinationView()
    writes, _ = submit(view, 1, "Often drives left", opponent="A2")

    assert not writes[0]["accepted"]
    assert view.shared_memory("A", 2) == []


def test_eviction_is_logged_and_old_snapshot_is_preserved():
    view = SimpleCoordinationView()

    for event_idx in range(1, 5):
        submit(view, event_idx, f"Observation {event_idx}")

    writes, _ = submit(view, 5, "Observation 5")

    assert writes[0]["evicted_ids"] == ["M01"]
    assert {entry.id for entry in view.shared_memory("A", 5)} == {
        "M01", "M02", "M03", "M04",
    }
    assert {entry.id for entry in view.shared_memory("A", 6)} == {
        "M02", "M03", "M04", "M05",
    }


def test_injected_embedder_is_used_by_coordination_view():
    view = SimpleCoordinationView(
        embedder=lambda text: [1.0, 0.0],
    )
    submit(view, 1, "Often drives left")
    writes, _ = submit(view, 2, "Prefers attacking the left side")

    assert writes[0]["merged_into"] == "M01"
    assert len(view.shared_memory("A", 3)) == 1
    assert view.shared_memory("A", 3)[0].confidence == 2