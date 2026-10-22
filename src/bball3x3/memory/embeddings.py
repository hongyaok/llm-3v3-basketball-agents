"""Lazy local sentence embeddings for WS4 memory merging."""

from typing import Any


class LocalEmbedder:
    """Callable adapter matching the stores' Embedder interface."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load_model(self) -> Any:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                'Install local embeddings with: pip install -e ".[embeddings]"'
            ) from exc

        return SentenceTransformer(self.model_name, device="cpu")

    def __call__(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("Embedding text must not be empty")

        if self._model is None:
            self._model = self._load_model()

        vector = self._model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [float(value) for value in vector]