"""Validated, bounded shared memory for one team."""

from typing import get_args

from bball3x3.memory.similarity import Embedder, cosine_similarity
from bball3x3.schemas.memory import (
    MemoryCategory,
    MemoryEntry,
    MemoryProposal,
)


class SharedMemoryStore:
    """One team's shared memory, reset by creating a new store per game."""

    def __init__(
        self,
        opponents: set[str],
        initial_entries: list[MemoryEntry] | None = None,
        *,
        embedder: Embedder | None = None,
        similarity_threshold: float = 0.80,
    ) -> None:
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("Similarity threshold must be between 0 and 1")

        self._embedder = embedder
        self._similarity_threshold = similarity_threshold
        self._embedding_cache: dict[str, tuple[float, ...]] = {}
        self._opponents = set(opponents)
        self._entries: list[MemoryEntry] = []
        self._next_id = 1

        initial = initial_entries or []
        ids = [entry.id for entry in initial]
        if len(ids) != len(set(ids)):
            raise ValueError("Initial memory IDs must be unique")

        for entry in initial:
            self._validate(
                MemoryProposal(
                    opponent=entry.opponent,
                    category=entry.category,
                    tendency=entry.tendency,
                )
            )
            self._entries.append(entry.model_copy(deep=True))

        # Never reuse an existing ID, including after eviction.
        for entry in self._entries:
            if not entry.id.startswith("M") or not entry.id[1:].isdigit():
                raise ValueError("Memory IDs must use the format M01, M02, ...")
            self._next_id = max(self._next_id, int(entry.id[1:]) + 1)

        groups: dict[tuple[str, str], int] = {}
        for entry in self._entries:
            group = (entry.opponent, entry.category)
            groups[group] = groups.get(group, 0) + 1
            if groups[group] > 4:
                raise ValueError("Initial memory exceeds four entries per group")

    def _validate(self, proposal: MemoryProposal) -> None:
        if proposal.opponent not in self._opponents:
            raise ValueError("Opponent must be an active opposing player")
        if proposal.category not in get_args(MemoryCategory):
            raise ValueError("Unknown memory category")
        if not proposal.tendency.strip():
            raise ValueError("Memory tendency must not be empty")

    def entries(self) -> list[MemoryEntry]:
        """Return copies of the current entries."""
        return [entry.model_copy(deep=True) for entry in self._entries]
    
    def _embedding(self, text: str) -> tuple[float, ...]:
        """Cache embeddings so repeated text is embedded only once."""
        if self._embedder is None:
            raise RuntimeError("No embedding function configured")

        if text not in self._embedding_cache:
            vector = tuple(float(value) for value in self._embedder(text))
            # Validate before caching.
            cosine_similarity(vector, vector)
            self._embedding_cache[text] = vector

        return self._embedding_cache[text]
    
    def write(
        self,
        proposal: MemoryProposal,
        *,
        player_id: str,
        event_idx: int,
    ) -> tuple[MemoryEntry, bool, list[str]]:
        """Return (written entry, merged, evicted IDs)."""
        self._validate(proposal)
        if event_idx < 1:
            raise ValueError("Event index must be positive")

        tendency = proposal.tendency.strip()
        group = [
            entry
            for entry in self._entries
            if entry.opponent == proposal.opponent
            and entry.category == proposal.category
        ]

        existing = next(
            (
                entry
                for entry in group
                if entry.tendency.strip().casefold() == tendency.casefold()
            ),
            None,
        )
        # Prefer an exact match; otherwise find the closest eligible entry.
        if existing is None and self._embedder is not None and group:
            proposed_vector = self._embedding(tendency)
            scored = [
                (
                    cosine_similarity(
                        proposed_vector,
                        self._embedding(candidate.tendency),
                    ),
                    candidate,
                )
                for candidate in group
            ]
            score, candidate = max(scored, key=lambda item: item[0])

            if score >= self._similarity_threshold:
                existing = candidate

        if existing is not None:
            existing.confidence += 1
            existing.decision_event = event_idx
            existing.observed_by = player_id
            return existing.model_copy(deep=True), True, []

        entry = MemoryEntry(
            id=f"M{self._next_id:02d}",
            opponent=proposal.opponent,
            category=proposal.category,
            tendency=tendency,
            confidence=1,
            observed_by=player_id,
            decision_event=event_idx,
        )
        
        # Compare the proposed entry with existing entries in this group.
        candidates = group + [entry]
        evicted_ids: list[str] = []

        if len(candidates) > 4:
            victim = min(
                candidates,
                key=lambda item: (
                    item.confidence,
                    item.decision_event,
                    item.id,
                ),
            )

            # A weaker proposal must not displace stronger memories.
            if victim.id == entry.id:
                raise ValueError(
                    "Memory capacity is full of higher-priority entries"
                )

            evicted_ids.append(victim.id)

        # Commit only after the proposal survives the capacity check.
        self._next_id += 1
        self._entries.append(entry)
        self._entries = [
            item for item in self._entries if item.id not in evicted_ids
        ]

        return entry.model_copy(deep=True), False, evicted_ids