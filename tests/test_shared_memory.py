"""Validation, merging, and capacity tests for shared memory."""

import pytest

from bball3x3.memory.shared import SharedMemoryStore
from bball3x3.schemas.memory import MemoryEntry, MemoryProposal


def proposal(tendency="Often drives left", **changes):
    fields = {
        "opponent": "B1",
        "category": "offensive_tendency",
        "tendency": tendency,
    }
    fields.update(changes)
    return MemoryProposal(**fields)


def write(store, tendency, event_idx):
    return store.write(
        proposal(tendency),
        player_id="A1",
        event_idx=event_idx,
    )


def test_initial_memory_is_copied():
    initial = MemoryEntry(
        id="M01",
        opponent="B1",
        category="offensive_tendency",
        tendency="Often drives left",
    )
    store = SharedMemoryStore({"B1"}, [initial])
    initial.tendency = "Changed outside store"

    assert store.entries()[0].tendency == "Often drives left"
    assert store.entries()[0].confidence == 1
    assert store.entries()[0].observed_by == "PREGAME"


@pytest.mark.parametrize("changes", [
    {"opponent": "A1"},
    {"opponent": "B9"},
    {"category": "invalid"},
    {"tendency": "   "},
])
def test_invalid_proposals_do_not_change_store(changes):
    store = SharedMemoryStore({"B1", "B2", "B3"})

    with pytest.raises(ValueError):
        store.write(
            proposal(**changes),
            player_id="A1",
            event_idx=1,
        )

    assert store.entries() == []


def test_exact_match_merges_and_increases_confidence():
    store = SharedMemoryStore({"B1"})
    first, merged, _ = write(store, "Often drives left", 1)
    second, merged_again, evicted = write(
        store, "  OFTEN DRIVES LEFT  ", 2
    )

    assert not merged
    assert merged_again
    assert second.id == first.id
    assert second.confidence == 2
    assert second.decision_event == 2
    assert evicted == []
    assert len(store.entries()) == 1


def test_capacity_evicts_lowest_confidence_then_oldest():
    store = SharedMemoryStore({"B1"})
    write(store, "Tendency one", 1)
    write(store, "Tendency two", 2)
    write(store, "Tendency three", 3)
    write(store, "Tendency four", 4)

    # Protect the oldest entry by increasing its confidence.
    write(store, "Tendency one", 5)
    entry, merged, evicted = write(store, "Tendency five", 6)

    assert entry.id == "M05"
    assert not merged
    assert evicted == ["M02"]
    assert {item.id for item in store.entries()} == {
        "M01", "M03", "M04", "M05",
    }

    # Evicted IDs must never be reused.
    next_entry, _, _ = write(store, "Tendency six", 7)
    assert next_entry.id == "M06"


def test_same_text_for_different_opponents_does_not_merge():
    store = SharedMemoryStore({"B1", "B2"})
    write(store, "Often drives left", 1)
    store.write(
        proposal(opponent="B2"),
        player_id="A1",
        event_idx=2,
    )

    assert len(store.entries()) == 2


def test_reads_cannot_mutate_store():
    store = SharedMemoryStore({"B1"})
    write(store, "Often drives left", 1)

    store.entries()[0].confidence = 999

    assert store.entries()[0].confidence == 1

def test_weaker_proposal_is_rejected_without_mutation_or_id_gap():
    store = SharedMemoryStore({"B1"})

    tendencies = ["First", "Second", "Third", "Fourth"]
    for event_idx, tendency in enumerate(tendencies, start=1):
        write(store, tendency, event_idx)

    # Raise all four existing memories to confidence 2.
    for event_idx, tendency in enumerate(tendencies, start=5):
        write(store, tendency, event_idx)

    before = store.entries()

    with pytest.raises(ValueError, match="higher-priority"):
        write(store, "Weaker new observation", 9)

    assert store.entries() == before

    # Another opponent/category group still has room.
    entry, merged, evicted = store.write(
        proposal(
            tendency="Leaves shooters open",
            category="defensive_tendency",
        ),
        player_id="A1",
        event_idx=10,
    )

    assert entry.id == "M05"
    assert not merged
    assert evicted == []