"""Category-filtered cosine retrieval over the offline FIBA rulebook index."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from bball3x3.engine.contact import referee_query_text
from bball3x3.schemas.referee import RefereeState

from .index import CATEGORIES, DEFAULT_INDEX_DIR, hash_embeddings


def categories_for_state(state: RefereeState) -> tuple[str, ...]:
    """Route event, contact and ball evidence to relevant rule categories."""
    event = state.current_event
    event_type = event.get("event_type")
    event_type = event_type.upper() if isinstance(event_type, str) else ""
    contact = state.contact_event
    shooting = (
        event.get("was_shooting") is True
        or event_type in {"SHOOT", "SHOT"}
        or state.ball.status == "IN_SHOT"
    )
    selected: list[str] = []

    def add(*names: str) -> None:
        for name in names:
            if name not in selected:
                selected.append(name)

    violation = event.get("judgement_violation")
    if violation == "GOALTENDING" or violation == "BASKET_INTERFERENCE" or event_type in {
        "GOALTENDING", "BASKET_INTERFERENCE",
    }:
        add("goaltending_interference")
    if violation == "STALLING" or event_type == "STALLING":
        add("stalling")

    if contact.contact_detected:
        contact_categories = {
            "BODY_CONTACT_DRIVE": ("blocking_charging", "personal_contact"),
            "REACH": ("illegal_use_of_hands", "personal_contact"),
            "SCREEN_CONTACT": ("screening", "personal_contact"),
            "LOOSE_BALL": ("loose_ball", "personal_contact"),
        }
        add(*contact_categories.get(contact.contact_type, ("personal_contact",)))
    elif state.ball.status == "IN_SHOT" or event_type in {"SHOOT", "SHOT"}:
        add("goaltending_interference")
    elif event_type == "REBOUND" or state.ball.status == "LOOSE":
        add("loose_ball", "personal_contact")

    if shooting:
        add("shooting_foul")
    if event.get("unsportsmanlike_contact") is True:
        add("unsportsmanlike", "free_throws")
    if event.get("technical_conduct") is True or event_type == "TECHNICAL":
        add("technical", "free_throws")
    if event_type in {"FREE_THROW", "FT"}:
        add("free_throws")
    if event_type == "TEAM_FOUL" or (
        contact.contact_detected and any(fouls >= 6 for fouls in state.team_fouls.values())
    ):
        add("team_fouls", "free_throws")
    if not selected:
        add("stalling")
    return tuple(selected)


@dataclass(frozen=True, slots=True)
class RetrievedRule:
    id: str
    category: str
    text: str
    page_start: int
    page_end: int
    score: float


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    query: str
    categories: tuple[str, ...]
    rules: tuple[RetrievedRule, ...]

    @property
    def chunk_ids(self) -> list[str]:
        return [rule.id for rule in self.rules]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuleRetriever:
    """Load one aligned index and reuse its encoder across per-state searches."""

    def __init__(
        self,
        index_dir: str | Path = DEFAULT_INDEX_DIR,
        *,
        expected_model: str | None = None,
    ) -> None:
        directory = Path(index_dir)
        manifest_path = directory / "index_manifest.json"
        chunks_path = directory / "chunks.jsonl"
        embeddings_path = directory / "embeddings.npy"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError(f"Unsupported rule index manifest: {manifest_path}")
        backend = manifest.get("embedding_backend")
        model = manifest.get("embedding_model")
        if backend not in {"hash", "sentence-transformers"} or not isinstance(model, str):
            raise ValueError(f"Invalid embedding metadata in {manifest_path}")
        if expected_model is not None and model != expected_model:
            raise ValueError(f"Index model {model!r} does not match {expected_model!r}")
        for path, key in (
            (chunks_path, "chunks_sha256"),
            (embeddings_path, "embeddings_sha256"),
        ):
            if _sha256(path) != manifest.get(key):
                raise ValueError(f"Rule index checksum mismatch: {path}")
        source = directory / str(manifest.get("source_pdf", ""))
        if source.is_file() and _sha256(source) != manifest.get("source_sha256"):
            raise ValueError(f"Rulebook changed since indexing: {source}")

        chunks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for line_number, line in enumerate(chunks_path.read_text(encoding="utf-8").splitlines(), 1):
            chunk = json.loads(line)
            if (
                not isinstance(chunk, dict)
                or not isinstance(chunk.get("id"), str)
                or not isinstance(chunk.get("text"), str)
                or chunk.get("category") not in CATEGORIES
                or chunk["id"] in seen
                or not isinstance(chunk.get("page_start"), int)
                or not isinstance(chunk.get("page_end"), int)
            ):
                raise ValueError(f"Invalid rule chunk at {chunks_path}:{line_number}")
            seen.add(chunk["id"])
            chunks.append(chunk)
        vectors = np.load(embeddings_path, allow_pickle=False)
        shape = manifest.get("embedding_shape")
        if (
            vectors.ndim != 2
            or vectors.shape[0] != len(chunks)
            or not isinstance(shape, list)
            or vectors.shape != tuple(shape)
            or len(chunks) != manifest.get("chunk_count")
            or not chunks
            or vectors.shape[1] == 0
            or not np.issubdtype(vectors.dtype, np.floating)
            or not np.isfinite(vectors).all()
        ):
            raise ValueError(f"Rule index vectors do not match chunks: {directory}")
        norms = np.linalg.norm(vectors, axis=1)
        if not np.all(norms > 0):
            raise ValueError(f"Rule index contains zero vectors: {embeddings_path}")
        if backend == "hash" and model != f"hashed-unigrams-v1-{vectors.shape[1]}":
            raise ValueError(f"Hash embedding model does not match dimension: {model}")
        self.chunks = tuple(chunks)
        self.vectors = np.asarray(vectors / norms[:, None], dtype=np.float32)
        self.backend = backend
        self.model_name = model
        self._encoder: Any = None

    def _encode_query(self, query: str) -> np.ndarray:
        if self.backend == "hash":
            return hash_embeddings([query], self.vectors.shape[1])[0]
        if self._encoder is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "Rule retrieval requires the optional 'rag' dependencies"
                ) from exc
            self._encoder = SentenceTransformer(self.model_name)
        return np.asarray(
            self._encoder.encode([query], convert_to_numpy=True, normalize_embeddings=True)[0],
            dtype=np.float32,
        )

    def retrieve(self, state: RefereeState, *, top_k: int = 3) -> RetrievalResult:
        """Return the highest-cosine excerpts among categories for this state."""
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        query = referee_query_text(state)
        categories = categories_for_state(state)
        eligible = [
            i for i, chunk in enumerate(self.chunks) if chunk["category"] in categories
        ]
        if not eligible:
            return RetrievalResult(query=query, categories=categories, rules=())
        vector = np.asarray(self._encode_query(query), dtype=np.float32)
        if vector.shape != (self.vectors.shape[1],) or not np.isfinite(vector).all():
            raise ValueError("Query embedding does not match rule index dimension")
        norm = np.linalg.norm(vector)
        if not norm:
            raise ValueError("Query embedding is zero")
        scores = self.vectors @ (vector / norm)
        ranked = sorted(eligible, key=lambda i: (-float(scores[i]), self.chunks[i]["id"]))
        rules = tuple(
            RetrievedRule(
                id=self.chunks[i]["id"],
                category=self.chunks[i]["category"],
                text=self.chunks[i]["text"],
                page_start=self.chunks[i]["page_start"],
                page_end=self.chunks[i]["page_end"],
                score=float(scores[i]),
            )
            for i in ranked[:top_k]
        )
        return RetrievalResult(query=query, categories=categories, rules=rules)
