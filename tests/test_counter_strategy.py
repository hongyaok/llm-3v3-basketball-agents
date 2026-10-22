"""Counter-strategy creation, merging, and reference counting."""

import pytest

from bball3x3.memory.counter_strategy import CounterStrategyStore
from bball3x3.schemas.memory import CSProposal


def write(
    store,
    opponent_strategy,
    counter_strategy,
    event_idx,
    side="offense",
):
    return store.write(
        CSProposal(
            opponent_strategy=opponent_strategy,
            counter_strategy=counter_strategy,
            side=side,
        ),
        player_id="A1",
        event_idx=event_idx,
    )


def test_starts_empty_and_assigns_keys():
    store = CounterStrategyStore()
    assert store.entries() == []

    first, merged = write(store, "Zone defense", "Move the ball", 1)
    second, _ = write(store, "Switching defense", "Attack mismatches", 2)

    assert first.key == "01"
    assert second.key == "02"
    assert not merged
    assert first.created_by == "A1"
    assert first.times_referenced == 0


def test_exact_match_updates_counter_and_preserves_key():
    store = CounterStrategyStore()
    first, _ = write(store, "Zone defense", "Move the ball", 1)
    store.reference(first.key)

    updated, merged = write(
        store, "  ZONE DEFENSE  ", "Attack the gaps", 2
    )

    assert merged
    assert updated.key == first.key
    assert updated.counter_strategy == "Attack the gaps"
    assert updated.decision_event == 2
    assert updated.times_referenced == 1
    assert len(store.entries()) == 1


def test_similar_strategy_merges():
    vectors = {
        "Zone defense": [1.0, 0.0],
        "Defenders protect areas": [0.9, 0.1],
        "Full court pressure": [0.0, 1.0],
    }
    store = CounterStrategyStore(embedder=vectors.__getitem__)

    write(store, "Zone defense", "Move the ball", 1)
    updated, merged = write(
        store, "Defenders protect areas", "Attack the gaps", 2
    )
    separate, merged_separate = write(
        store, "Full court pressure", "Use quick passes", 3
    )

    assert merged
    assert updated.key == "01"
    assert updated.counter_strategy == "Attack the gaps"
    assert not merged_separate
    assert separate.key == "02"


def test_different_sides_do_not_merge():
    store = CounterStrategyStore(embedder=lambda text: [1.0, 0.0])

    write(store, "Switching", "Attack mismatches", 1, side="offense")
    _, merged = write(
        store, "Switching", "Communicate assignments", 2, side="defense"
    )

    assert not merged
    assert len(store.entries()) == 2


@pytest.mark.parametrize("opponent_strategy,counter_strategy", [
    ("   ", "Move the ball"),
    ("Zone defense", "   "),
])
def test_empty_descriptions_are_rejected(
    opponent_strategy, counter_strategy
):
    store = CounterStrategyStore()

    with pytest.raises(ValueError, match="must not be empty"):
        write(store, opponent_strategy, counter_strategy, 1)

    assert store.entries() == []


def test_reference_counts_only_existing_keys():
    store = CounterStrategyStore()
    write(store, "Zone defense", "Move the ball", 1)

    assert store.reference("01")
    assert store.reference("01")
    assert not store.reference("99")
    assert store.entries()[0].times_referenced == 2


def test_returned_entries_are_copies():
    store = CounterStrategyStore()
    entry, _ = write(store, "Zone defense", "Move the ball", 1)

    entry.counter_strategy = "Changed outside store"
    store.entries()[0].times_referenced = 999

    stored = store.entries()[0]
    assert stored.counter_strategy == "Move the ball"
    assert stored.times_referenced == 0