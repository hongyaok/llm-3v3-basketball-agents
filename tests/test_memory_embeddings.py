"""Local embedding adapter tests without model downloads."""

import pytest

from bball3x3.memory.embeddings import LocalEmbedder


class FakeEncoder:
    def __init__(self):
        self.calls = []

    def encode(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return [0.6, 0.8]


def test_model_is_loaded_once_and_encode_options_are_explicit(monkeypatch):
    encoder = FakeEncoder()
    loads = []

    def load_model(self):
        loads.append(self.model_name)
        return encoder

    monkeypatch.setattr(LocalEmbedder, "_load_model", load_model)
    embedder = LocalEmbedder("test-model")

    assert loads == []
    assert embedder("Drives left") == [0.6, 0.8]
    assert embedder("Shoots outside") == [0.6, 0.8]
    assert loads == ["test-model"]
    assert encoder.calls[0] == (
        "Drives left",
        {
            "normalize_embeddings": True,
            "show_progress_bar": False,
        },
    )


def test_empty_text_does_not_load_model(monkeypatch):
    def unexpected_load(self):
        pytest.fail("Model should not load for empty text")

    monkeypatch.setattr(LocalEmbedder, "_load_model", unexpected_load)

    with pytest.raises(ValueError, match="must not be empty"):
        LocalEmbedder()("   ")