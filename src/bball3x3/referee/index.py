"""Build a versioned, clause-level index of the local FIBA 3x3 rules PDF."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import numpy as np

try:
    from pypdf import PdfReader
except ImportError:  # A saved index can be queried without the PDF parser.
    PdfReader = None

DEFAULT_RULEBOOK = Path("data/rules/fiba-3x3-basketball-rules-full-version.pdf")
DEFAULT_INDEX_DIR = Path("data/rules")
DEFAULT_SENTENCE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EmbeddingBackend = Literal["hash", "sentence-transformers"]

CATEGORIES = (
    "personal_contact",
    "blocking_charging",
    "screening",
    "shooting_foul",
    "illegal_use_of_hands",
    "loose_ball",
    "unsportsmanlike",
    "technical",
    "goaltending_interference",
    "stalling",
    "free_throws",
    "team_fouls",
)

_ARTICLE = re.compile(r"^Art\.\s*(\d{1,2})\s+(.+)$")
_CLAUSE = re.compile(r"^(\d{1,2}\.\d+(?:\.\d+)?)\s+(.+)$")
_PAGE_FOOTER = re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9]+")


def _category(article: int, clause: str) -> str | None:
    """Keep only referee-relevant clauses; assign one planned category each."""
    section = int(clause.split(".")[1])
    if article == 15:
        return "shooting_foul"
    if article == 29 and section == 1:
        return "stalling"
    if article == 31:
        return "goaltending_interference"
    if article in (32, 35):
        return "personal_contact"
    if article == 33:
        if section in (4, 8, 9, 10):
            return "blocking_charging"
        if section == 7:
            return "screening"
        if section == 11:
            return "illegal_use_of_hands"
        if section == 5:
            return "loose_ball"
        return "personal_contact"
    if article == 34:
        return "shooting_foul" if clause == "34.2.2" else "personal_contact"
    if article == 36:
        return "technical"
    if article == 37:
        return "unsportsmanlike"
    if article == 41:
        return "team_fouls"
    if article == 43:
        return "free_throws"
    return None


def _join_lines(lines: list[str]) -> str:
    parts: list[str] = []
    for line in lines:
        clean = " ".join(line.split())
        if not clean:
            continue
        if parts and parts[-1].endswith("-") and clean[0].islower():
            parts[-1] = parts[-1][:-1] + clean
        else:
            parts.append(clean)
    return " ".join(parts)


def extract_rule_chunks(pdf_path: str | Path) -> tuple[list[dict[str, Any]], int]:
    """Extract numbered clauses, retaining their article and source PDF pages."""
    if PdfReader is None:
        raise RuntimeError("Building the rule index requires pypdf")
    reader = PdfReader(str(pdf_path))
    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    article: int | None = None
    title = ""
    clause: str | None = None
    lines: list[str] = []
    first_page = last_page = 0

    def flush() -> None:
        if article is None or clause is None:
            return
        category = _category(article, clause)
        body = _join_lines(lines)
        if category is None or not body:
            return
        rule_id = f"R{clause}"
        if rule_id in seen:
            raise ValueError(f"Duplicate rule ID {rule_id} in {pdf_path}")
        seen.add(rule_id)
        chunks.append({
            "id": rule_id,
            "article": article,
            "article_title": title,
            "clause": clause,
            "category": category,
            "page_start": first_page,
            "page_end": last_page,
            "text": f"Art. {article} {title}; {clause} {body}",
        })

    for page_number, page in enumerate(reader.pages, start=1):
        for raw_line in (page.extract_text(extraction_mode="layout") or "").splitlines():
            line = raw_line.strip()
            if not line or _PAGE_FOOTER.fullmatch(line):
                continue
            article_match = _ARTICLE.fullmatch(line)
            if article_match:
                flush()
                article = int(article_match.group(1))
                title = _join_lines([article_match.group(2)])
                clause = None
                lines = []
                continue
            clause_match = _CLAUSE.fullmatch(line)
            if clause_match and article is not None:
                number = clause_match.group(1)
                if int(number.split(".")[0]) == article:
                    flush()
                    clause = number
                    lines = [clause_match.group(2)]
                    first_page = last_page = page_number
                    continue
            if clause is not None:
                lines.append(line)
                last_page = page_number
    flush()
    if not chunks:
        raise ValueError(f"No relevant numbered rule clauses found in {pdf_path}")
    return chunks, len(reader.pages)


def hash_embeddings(texts: list[str], dimension: int = 2048) -> np.ndarray:
    """Deterministic, local lexical vectors; no model download or API key needed."""
    if dimension < 128:
        raise ValueError("Hash embedding dimension must be at least 128")
    vectors = np.zeros((len(texts), dimension), dtype=np.float32)
    for row, text in enumerate(texts):
        counts = Counter(_TOKEN.findall(text.lower()))
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            column = int.from_bytes(digest, "big") % dimension
            vectors[row, column] += 1.0 + math.log(count)
        norm = np.linalg.norm(vectors[row])
        if norm:
            vectors[row] /= norm
    return vectors


def embed_chunks(
    texts: list[str], backend: EmbeddingBackend, model: str | None = None,
    hash_dimension: int = 2048,
) -> tuple[np.ndarray, str]:
    if backend == "hash":
        return hash_embeddings(texts, hash_dimension), f"hashed-unigrams-v1-{hash_dimension}"
    if backend != "sentence-transformers":
        raise ValueError(f"Unknown embedding backend: {backend}")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "Sentence-transformer indexing requires the optional 'rag' dependencies"
        ) from exc
    model_name = model or DEFAULT_SENTENCE_MODEL
    encoder = SentenceTransformer(model_name)
    vectors = encoder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return np.asarray(vectors, dtype=np.float32), model_name


def build_index(
    pdf_path: str | Path = DEFAULT_RULEBOOK,
    output_dir: str | Path = DEFAULT_INDEX_DIR,
    *,
    backend: EmbeddingBackend = "sentence-transformers",
    model: str | None = None,
    hash_dimension: int = 2048,
    force: bool = False,
) -> dict[str, Any]:
    """Write aligned JSONL chunks, NPY vectors and a provenance manifest."""
    source = Path(pdf_path)
    if not source.is_file():
        raise FileNotFoundError(f"Rulebook PDF not found: {source}")
    destination = Path(output_dir)
    names = ("chunks.jsonl", "embeddings.npy", "index_manifest.json")
    existing = [name for name in names if (destination / name).exists()]
    if existing and not force:
        raise FileExistsError(
            f"Index files already exist in {destination}: {', '.join(existing)}; use --force"
        )

    chunks, page_count = extract_rule_chunks(source)
    category_counts = Counter(chunk["category"] for chunk in chunks)
    missing = set(CATEGORIES) - category_counts.keys()
    if missing:
        raise ValueError(f"Rulebook extraction missed categories: {', '.join(sorted(missing))}")
    vectors, model_name = embed_chunks(
        [chunk["text"] for chunk in chunks], backend, model, hash_dimension,
    )
    if vectors.ndim != 2 or vectors.shape[0] != len(chunks) or not np.isfinite(vectors).all():
        raise ValueError("Embedding matrix does not align with the extracted chunks")

    destination.mkdir(parents=True, exist_ok=True)
    temporary: list[Path] = []
    try:
        for name in names:
            with tempfile.NamedTemporaryFile(dir=destination, prefix=f".{name}.",
                                             delete=False) as stream:
                temporary.append(Path(stream.name))
        chunk_tmp, embedding_tmp, manifest_tmp = temporary
        # The manifest hashes raw bytes, so the index must have the same line
        # endings on every OS (including Windows with core.autocrlf enabled).
        with chunk_tmp.open("w", encoding="utf-8", newline="\n") as stream:
            for chunk in chunks:
                stream.write(json.dumps(chunk, ensure_ascii=False, sort_keys=True) + "\n")
        with embedding_tmp.open("wb") as stream:
            np.save(stream, vectors, allow_pickle=False)

        manifest = {
            "schema_version": 1,
            "source_pdf": source.name,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "page_count": page_count,
            "chunk_count": len(chunks),
            "category_counts": {name: category_counts[name] for name in CATEGORIES},
            "embedding_backend": backend,
            "embedding_model": model_name,
            "embedding_shape": list(vectors.shape),
            "chunks_sha256": hashlib.sha256(chunk_tmp.read_bytes()).hexdigest(),
            "embeddings_sha256": hashlib.sha256(embedding_tmp.read_bytes()).hexdigest(),
        }
        with manifest_tmp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        for temporary_path, name in zip(temporary, names, strict=True):
            temporary_path.chmod(0o644)
            os.replace(temporary_path, destination / name)
        return manifest
    finally:
        for temporary_path in temporary:
            temporary_path.unlink(missing_ok=True)
