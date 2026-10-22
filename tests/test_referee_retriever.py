"""Category routing and index-backed per-state retrieval."""

import hashlib
import json

import numpy as np
import pytest

from bball3x3.engine.contact import referee_query_text
from bball3x3.referee import RuleRetriever, categories_for_state
from bball3x3.referee.index import hash_embeddings
from bball3x3.schemas.referee import ContactEvent, RefereeState
from bball3x3.schemas.state import BallState


def _state(*, event=None, contact_type=None, ball_status="HELD", team_fouls=None):
    return RefereeState(
        ball=BallState(status=ball_status, pos=(0, 0)),
        current_event=event or {},
        contact_event=ContactEvent(
            contact_detected=contact_type is not None,
            contact_type=contact_type,
        ),
        team_fouls=team_fouls or {"A": 0, "B": 0},
    )


def _write_index(directory, chunks, vectors):
    directory.mkdir()
    chunks_path = directory / "chunks.jsonl"
    vectors_path = directory / "embeddings.npy"
    chunks_path.write_text("".join(json.dumps(chunk) + "\n" for chunk in chunks))
    np.save(vectors_path, vectors.astype(np.float32))
    manifest = {
        "schema_version": 1,
        "source_pdf": "rulebook.pdf",
        "source_sha256": hashlib.sha256(b"rulebook").hexdigest(),
        "chunk_count": len(chunks),
        "embedding_backend": "hash",
        "embedding_model": f"hashed-unigrams-v1-{vectors.shape[1]}",
        "embedding_shape": list(vectors.shape),
        "chunks_sha256": hashlib.sha256(chunks_path.read_bytes()).hexdigest(),
        "embeddings_sha256": hashlib.sha256(vectors_path.read_bytes()).hexdigest(),
    }
    (directory / "rulebook.pdf").write_bytes(b"rulebook")
    (directory / "index_manifest.json").write_text(json.dumps(manifest))
    return manifest


def _chunk(rule_id, category, text):
    return {
        "id": rule_id, "category": category, "text": text,
        "page_start": 10, "page_end": 11,
    }


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(contact_type="SCREEN_CONTACT"), ("screening",)),
        (_state(contact_type="BODY_CONTACT_DRIVE"), ("blocking_charging",)),
        (_state(contact_type="REACH"), ("illegal_use_of_hands",)),
        (_state(contact_type="LOOSE_BALL"), ("loose_ball",)),
        (_state(ball_status="IN_SHOT"), ("goaltending_interference", "shooting_foul")),
        (_state(event={"event_type": "REBOUND"}), ("loose_ball",)),
        (_state(event={"event_type": "SCREEN"}), ("screening",)),
        (_state(event={"event_type": "SHOOT"}, contact_type="BODY_CONTACT_DRIVE"),
         ("shooting_foul",)),
        (_state(event={"offensive_contact": True}, contact_type="BODY_CONTACT_DRIVE"),
         ("blocking_charging",)),
        (_state(event={"event_type": "HOLD"}), ("stalling",)),
        (_state(event={"technical_conduct": True}), ("technical",)),
        (_state(event={"judgement_violation": "GOALTENDING"}),
         ("goaltending_interference",)),
        (_state(contact_type="REACH", team_fouls={"A": 6, "B": 0}),
         ("illegal_use_of_hands", "team_fouls", "free_throws")),
    ],
)
def test_categories_for_state(state, expected):
    assert categories_for_state(state) == expected


def test_malformed_event_marker_does_not_break_routing():
    assert categories_for_state(_state(event={"judgement_violation": []})) == ("stalling",)


def test_retrieval_filters_then_ranks_with_stable_ties(tmp_path, monkeypatch):
    chunks = [
        _chunk("R33.8", "screening", "screen B"),
        _chunk("R33.7", "screening", "screen A"),
        _chunk("R33.2", "personal_contact", "general contact"),
        _chunk("R33.9", "blocking_charging", "charge"),
    ]
    vectors = np.zeros((4, 128), dtype=np.float32)
    vectors[0, 0] = vectors[1, 0] = vectors[3, 0] = 1
    vectors[2, :2] = [0.6, 0.8]
    _write_index(tmp_path / "index", chunks, vectors)
    retriever = RuleRetriever(tmp_path / "index")
    query_vector = np.zeros(128, dtype=np.float32)
    query_vector[0] = 1
    monkeypatch.setattr(retriever, "_encode_query", lambda _query: query_vector)
    state = _state(contact_type="SCREEN_CONTACT")

    result = retriever.retrieve(state)

    assert result.query == referee_query_text(state)
    assert result.categories == ("screening",)
    assert result.chunk_ids == ["R33.7", "R33.8"]
    assert result.rules[0].page_start == 10
    assert result.rules[0].page_end == 11
    assert result.rules[0].text == "screen A"
    assert [rule.score for rule in result.rules] == pytest.approx([1, 1])
    assert retriever.retrieve(state, top_k=1).chunk_ids == ["R33.7"]
    with pytest.raises(ValueError, match="positive integer"):
        retriever.retrieve(state, top_k=0)


def test_hash_backend_embeds_query_using_index_dimension(tmp_path, monkeypatch):
    chunks = [
        _chunk("R33.7", "screening", "screen contact legal"),
        _chunk("R33.1", "personal_contact", "personal foul"),
    ]
    vectors = hash_embeddings([chunk["text"] for chunk in chunks], 128)
    _write_index(tmp_path / "index", chunks, vectors)
    retriever = RuleRetriever(tmp_path / "index")
    monkeypatch.setattr("bball3x3.referee.retriever.referee_query_text",
                        lambda _state: "screen contact legal")

    result = retriever.retrieve(_state(contact_type="SCREEN_CONTACT"))

    assert result.chunk_ids[0] == "R33.7"
    assert result.rules[0].score == pytest.approx(1, abs=1e-6)


def test_index_checks_artifact_checksum_and_model(tmp_path):
    chunks = [_chunk("R33.7", "screening", "screen")]
    vectors = hash_embeddings(["screen"], 128)
    directory = tmp_path / "index"
    _write_index(directory, chunks, vectors)
    with pytest.raises(ValueError, match="does not match"):
        RuleRetriever(directory, expected_model="different-model")
    (directory / "chunks.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        RuleRetriever(directory)


def test_index_rejects_misaligned_embeddings(tmp_path):
    chunks = [_chunk("R33.7", "screening", "screen")]
    vectors = np.ones((2, 128), dtype=np.float32)
    directory = tmp_path / "index"
    _write_index(directory, chunks, vectors)
    with pytest.raises(ValueError, match="do not match chunks"):
        RuleRetriever(directory)


def test_retrieval_fails_clearly_on_wrong_query_dimension(tmp_path, monkeypatch):
    chunks = [_chunk("R33.7", "screening", "screen")]
    directory = tmp_path / "index"
    _write_index(directory, chunks, hash_embeddings(["screen"], 128))
    retriever = RuleRetriever(directory)
    monkeypatch.setattr(retriever, "_encode_query", lambda _query: np.ones(64))
    with pytest.raises(ValueError, match="dimension"):
        retriever.retrieve(_state(contact_type="SCREEN_CONTACT"))
