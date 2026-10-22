"""Offline retrieval evaluation over the hand-labelled Phase B cases."""

import json
from types import SimpleNamespace

import pytest

from bball3x3.referee import RuleRetriever
from bball3x3.referee.index import _category
from bball3x3.referee.retrieval_validation import (
    DEFAULT_GOLD,
    evaluate_retrieval,
    load_gold,
    main,
)
from bball3x3.referee.validation import load_cases


def test_checked_in_gold_matches_cases_and_saved_index():
    cases = load_cases()
    labels = load_gold()
    retriever = RuleRetriever("data/rules")

    assert len(cases) == 40
    assert len(labels) == 26
    assert retriever.backend == "sentence-transformers"
    assert len({case["id"] for case in cases}) == 40
    case_ids = {case["id"] for case in cases}
    indexed_ids = {chunk["id"] for chunk in retriever.chunks}
    assert all(label.case_id in case_ids for label in labels)
    assert all(set(label.gold_rule_ids) <= indexed_ids for label in labels)
    assert all(
        chunk["category"] == _category(chunk["article"], chunk["clause"])
        for chunk in retriever.chunks
    )
    assert {chunk["article"] for chunk in retriever.chunks}.isdisjoint({38, 39})


class _FakeRetriever:
    backend = "hash"
    model_name = "test-model"
    chunks = (
        {"id": "R33.7", "category": "screening"},
        {"id": "R33.8", "category": "blocking_charging"},
        {"id": "R33.9", "category": "blocking_charging"},
        {"id": "R33.1", "category": "personal_contact"},
        {"id": "R29.1.1", "category": "stalling"},
    )

    def retrieve(self, state, *, top_k):
        assert top_k == 3
        event = state.current_event
        if event.get("offensive_contact"):
            return SimpleNamespace(
                chunk_ids=["R33.9", "R33.1"],
                categories=("blocking_charging", "personal_contact"),
            )
        if state.contact_event.contact_detected:
            return SimpleNamespace(
                chunk_ids=["R33.1", "R33.7"],
                categories=("screening", "personal_contact"),
            )
        return SimpleNamespace(chunk_ids=["R29.1.1"], categories=("stalling",))


def test_evaluation_separates_hits_ranking_and_filter_misses():
    selected = {"screen_a2_b2", "drive_offensive_a1", "no_contact_screen"}
    cases = [case for case in load_cases() if case["id"] in selected]
    labels = [label for label in load_gold() if label.case_id in selected]

    report = evaluate_retrieval(_FakeRetriever(), cases, labels)

    assert report["hit_at_3"] == {"hits": 1, "total": 3, "rate": 1 / 3}
    assert report["category_filter_recall"] == {
        "eligible": 2, "total": 3, "rate": 2 / 3,
    }
    rows = {row["case_id"]: row for row in report["cases"]}
    assert rows["screen_a2_b2"]["first_hit_rank"] == 2
    assert rows["screen_a2_b2"]["miss_reason"] is None
    assert rows["drive_offensive_a1"]["category_eligible"] is True
    assert rows["drive_offensive_a1"]["hit_at_3"] is False
    assert rows["drive_offensive_a1"]["miss_reason"] == "ranking"
    assert rows["no_contact_screen"]["category_eligible"] is False
    assert rows["no_contact_screen"]["first_hit_rank"] is None
    assert rows["no_contact_screen"]["miss_reason"] == "category_filter"
    assert report["by_call_type"]["OFFENSIVE_FOUL"] == {
        "hits": 1, "total": 2, "rate": 0.5,
    }


def test_invalid_gold_and_missing_index_clause_are_reported(tmp_path):
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"case_id":"screen_a2_b2","gold_rule_ids":["R33.7"]}\n'
        '{"case_id":"screen_a2_b2","gold_rule_ids":["R33.7"]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"duplicate.jsonl:2"):
        load_gold(duplicate)

    missing = tmp_path / "missing.jsonl"
    missing.write_text(
        '{"case_id":"screen_a2_b2","gold_rule_ids":["R999"]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Gold rules absent from index.*R999"):
        evaluate_retrieval(_FakeRetriever(), load_cases(), load_gold(missing))


def test_cli_emits_machine_readable_report(monkeypatch, capsys):
    monkeypatch.setattr(
        "bball3x3.referee.retrieval_validation.RuleRetriever", lambda _path: _FakeRetriever()
    )
    assert DEFAULT_GOLD.is_file()

    assert main([]) == 2  # the small fake index cannot contain every checked-in gold clause
    assert "Gold rules absent from index" in capsys.readouterr().err

    cases = [case for case in load_cases() if case["id"] == "screen_a2_b2"]
    labels = [label for label in load_gold() if label.case_id == "screen_a2_b2"]
    monkeypatch.setattr("bball3x3.referee.retrieval_validation.load_cases", lambda _path: cases)
    monkeypatch.setattr("bball3x3.referee.retrieval_validation.load_gold", lambda _path: labels)
    assert main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["hit_at_3"] == {"hits": 1, "total": 1, "rate": 1.0}
