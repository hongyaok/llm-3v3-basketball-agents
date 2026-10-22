"""Cosine similarity and semantic memory merging."""

import pytest

from bball3x3.memory.shared import SharedMemoryStore
from bball3x3.memory.similarity import cosine_similarity
from bball3x3.schemas.memory import MemoryProposal


def write(store, tendency, event_idx, category="offensive_tendency"):
    return store.write(
        MemoryProposal(
            opponent="B1",
            category=category,
            tendency=tendency,
        ),
        player_id="A1",
        event_idx=event_idx,
    )


def test_cosine_similarity():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0)
    assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1)


@pytest.mark.parametrize("left,right", [
    ([], []),
    ([1], [1, 0]),
    ([0, 0], [1, 0]),
    ([float("nan"), 0], [1, 0]),
    ([float("inf"), 0], [1, 0]),
])
def test_invalid_vectors(left, right):
    with pytest.raises(ValueError):
        cosine_similarity(left, right)


def test_similar_wording_merges_but_different_tendency_does_not():
    vectors = {
        "Often drives left": [1.0, 0.0],
        "Prefers attacking the left side": [0.9, 0.1],
        "Usually shoots from outside": [0.0, 1.0],
    }
    store = SharedMemoryStore({"B1"}, embedder=vectors.__getitem__)

    first, _, _ = write(store, "Often drives left", 1)
    merged_entry, merged, _ = write(
        store, "Prefers attacking the left side", 2
    )
    different, merged_different, _ = write(
        store, "Usually shoots from outside", 3
    )

    assert merged
    assert merged_entry.id == first.id
    assert merged_entry.confidence == 2
    assert not merged_different
    assert different.id != first.id
    assert len(store.entries()) == 2


def test_similarity_does_not_merge_across_categories():
    store = SharedMemoryStore(
        {"B1"},
        embedder=lambda text: [1.0, 0.0],
    )

    write(store, "First observation", 1)
    _, merged, _ = write(
        store,
        "Second observation",
        2,
        category="defensive_tendency",
    )

    assert not merged
    assert len(store.entries()) == 2


def test_threshold_is_inclusive():
    store = SharedMemoryStore(
        {"B1"},
        embedder=lambda text: [1.0, 0.0],
        similarity_threshold=1.0,
    )

    write(store, "First wording", 1)
    _, merged, _ = write(store, "Second wording", 2)

    assert merged


def test_embedding_cache():
    calls = []

    def embed(text):
        calls.append(text)
        return [1.0, 0.0]

    store = SharedMemoryStore({"B1"}, embedder=embed)

    write(store, "First wording", 1)
    write(store, "Second wording", 2)
    write(store, "Second wording", 3)

    assert calls.count("First wording") == 1
    assert calls.count("Second wording") == 1


def test_invalid_embedding_does_not_mutate_memory():
    store = SharedMemoryStore(
        {"B1"},
        embedder=lambda text: [0.0, 0.0],
    )
    write(store, "First observation", 1)

    with pytest.raises(ValueError):
        write(store, "Second observation", 2)

    assert len(store.entries()) == 1
    assert store.entries()[0].confidence == 1