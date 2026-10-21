"""Offline rulebook indexing stays deterministic and auditable."""

import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

from bball3x3.cli import app
from bball3x3.referee import index as rule_index


def test_clause_extraction_keeps_ids_categories_and_page_ranges(monkeypatch):
    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self, *, extraction_mode):
            assert extraction_mode == "layout"
            return self.text

    class Reader:
        def __init__(self, path):
            assert path == "book.pdf"
            self.pages = [
                Page("Art. 33 Contact: General principles\n"
                     "33.7 Screening: Legal and illegal\n"
                     "A screen can be legal.\nPage 1 of 2\n"),
                Page("An illegal screen makes contact.\n"
                     "33.8 Charging\nA charge is contact.\n"),
            ]

    monkeypatch.setattr(rule_index, "PdfReader", Reader)
    chunks, pages = rule_index.extract_rule_chunks("book.pdf")
    assert pages == 2
    assert [(chunk["id"], chunk["category"]) for chunk in chunks] == [
        ("R33.7", "screening"), ("R33.8", "blocking_charging"),
    ]
    assert chunks[0]["page_start"] == 1
    assert chunks[0]["page_end"] == 2
    assert "illegal screen" in chunks[0]["text"]
    assert "Page 1 of 2" not in chunks[0]["text"]


def test_hash_embeddings_are_deterministic_and_unit_length():
    first = rule_index.hash_embeddings(["screen contact foul", "screen screen illegal"])
    second = rule_index.hash_embeddings(["screen contact foul", "screen screen illegal"])
    np.testing.assert_array_equal(first, second)
    np.testing.assert_allclose(np.linalg.norm(first, axis=1), [1.0, 1.0], rtol=1e-6)
    assert first.dtype == np.float32


def test_semantic_backend_uses_configured_model_and_normalized_vectors(monkeypatch):
    class Encoder:
        def __init__(self, model):
            assert model == rule_index.DEFAULT_SENTENCE_MODEL

        def encode(self, texts, *, convert_to_numpy, normalize_embeddings):
            assert texts == ["one rule", "another rule"]
            assert convert_to_numpy and normalize_embeddings
            return np.array([[1.0, 0.0], [0.0, 1.0]])

    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=Encoder))
    vectors, model = rule_index.embed_chunks(
        ["one rule", "another rule"], "sentence-transformers",
    )
    assert model == rule_index.DEFAULT_SENTENCE_MODEL
    assert vectors.shape == (2, 2)
    assert vectors.dtype == np.float32


def test_build_index_writes_aligned_artifacts_and_refuses_overwrite(tmp_path, monkeypatch):
    pdf = tmp_path / "rulebook.pdf"
    pdf.write_bytes(b"mock PDF bytes")
    chunks = [
        {"id": f"R{i}.1", "category": category, "text": f"Rule {category}",
         "article": i, "article_title": category, "clause": f"{i}.1",
         "page_start": i, "page_end": i}
        for i, category in enumerate(rule_index.CATEGORIES, start=1)
    ]
    monkeypatch.setattr(rule_index, "extract_rule_chunks", lambda path: (chunks, 74))
    output = tmp_path / "index"
    manifest = rule_index.build_index(pdf, output, backend="hash")
    assert manifest["chunk_count"] == len(rule_index.CATEGORIES)
    assert manifest["embedding_shape"] == [len(chunks), 2048]
    assert manifest["embedding_backend"] == "hash"
    saved = [json.loads(line) for line in (output / "chunks.jsonl").read_text().splitlines()]
    assert [chunk["id"] for chunk in saved] == [chunk["id"] for chunk in chunks]
    matrix = np.load(output / "embeddings.npy", allow_pickle=False)
    assert matrix.shape == tuple(manifest["embedding_shape"])
    assert json.loads((output / "index_manifest.json").read_text()) == manifest
    with pytest.raises(FileExistsError, match="--force"):
        rule_index.build_index(pdf, output, backend="hash")
    assert rule_index.build_index(pdf, output, backend="hash", force=True) == manifest


def test_cli_build_index_exposes_offline_builder(tmp_path, monkeypatch):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"mock PDF bytes")
    chunks = [
        {"id": f"R{i}.1", "category": category, "text": category,
         "article": i, "article_title": category, "clause": f"{i}.1",
         "page_start": i, "page_end": i}
        for i, category in enumerate(rule_index.CATEGORIES, start=1)
    ]
    monkeypatch.setattr(rule_index, "extract_rule_chunks", lambda path: (chunks, 74))
    output = tmp_path / "index"
    result = CliRunner().invoke(
        app, ["build-index", str(pdf), "--output-dir", str(output), "--backend", "hash"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["chunk_count"] == len(chunks)
