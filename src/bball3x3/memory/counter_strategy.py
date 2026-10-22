"""Per-team counter-strategies with similarity merging."""

from bball3x3.memory.similarity import Embedder, cosine_similarity
from bball3x3.schemas.memory import CSEntry, CSProposal


class CounterStrategyStore:
    """Starts empty for each team in each game."""

    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        similarity_threshold: float = 0.80,
    ) -> None:
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("Similarity threshold must be between 0 and 1")

        self._embedder = embedder
        self._similarity_threshold = similarity_threshold
        self._embedding_cache: dict[str, tuple[float, ...]] = {}
        self._entries: list[CSEntry] = []
        self._next_key = 1

    def entries(self) -> list[CSEntry]:
        return [entry.model_copy(deep=True) for entry in self._entries]

    def _embedding(self, text: str) -> tuple[float, ...]:
        if self._embedder is None:
            raise RuntimeError("No embedding function configured")

        if text not in self._embedding_cache:
            vector = tuple(float(value) for value in self._embedder(text))
            cosine_similarity(vector, vector)
            self._embedding_cache[text] = vector

        return self._embedding_cache[text]

    def write(
        self,
        proposal: CSProposal,
        *,
        player_id: str,
        event_idx: int,
    ) -> tuple[CSEntry, bool]:
        """Return (stored entry, merged)."""
        opponent_strategy = proposal.opponent_strategy.strip()
        counter_strategy = proposal.counter_strategy.strip()

        if not opponent_strategy or not counter_strategy:
            raise ValueError("Strategy descriptions must not be empty")
        if event_idx < 1:
            raise ValueError("Event index must be positive")

        candidates = [
            entry
            for entry in self._entries
            if entry.side == proposal.side
        ]

        existing = next(
            (
                entry
                for entry in candidates
                if entry.opponent_strategy.casefold()
                == opponent_strategy.casefold()
            ),
            None,
        )

        if existing is None and self._embedder is not None and candidates:
            proposed_vector = self._embedding(opponent_strategy)
            scored = [
                (
                    cosine_similarity(
                        proposed_vector,
                        self._embedding(entry.opponent_strategy),
                    ),
                    entry,
                )
                for entry in candidates
            ]
            score, candidate = max(scored, key=lambda item: item[0])

            if score >= self._similarity_threshold:
                existing = candidate

        if existing is not None:
            existing.counter_strategy = counter_strategy
            existing.decision_event = event_idx
            return existing.model_copy(deep=True), True

        entry = CSEntry(
            key=f"{self._next_key:02d}",
            side=proposal.side,
            opponent_strategy=opponent_strategy,
            counter_strategy=counter_strategy,
            created_by=player_id,
            decision_event=event_idx,
            times_referenced=0,
        )
        self._next_key += 1
        self._entries.append(entry)
        return entry.model_copy(deep=True), False

    def reference(self, key: str) -> bool:
        """Count a reference after the caller checks event-time visibility."""
        for entry in self._entries:
            if entry.key == key:
                entry.times_referenced += 1
                return True
        return False