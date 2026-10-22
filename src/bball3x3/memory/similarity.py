"""Embedding interfaces and cosine similarity for memory stores."""

from collections.abc import Callable, Sequence
from math import isfinite, sqrt

Embedder = Callable[[str], Sequence[float]]


def cosine_similarity(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    """Compare finite, nonzero vectors of equal length."""
    if len(left) != len(right) or len(left) == 0:
        raise ValueError("Embedding dimensions must match and be nonempty")

    if not all(isfinite(value) for value in (*left, *right)):
        raise ValueError("Embeddings must contain finite values")

    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))

    if left_norm == 0 or right_norm == 0:
        raise ValueError("Embeddings must have nonzero magnitude")

    score = sum(a * b for a, b in zip(left, right)) / (
        left_norm * right_norm
    )
    return max(-1.0, min(1.0, score))