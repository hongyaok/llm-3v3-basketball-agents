"""CoordinationView protocol and WS3 implementations (WS3 §3.2 & §3.6)."""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from bball3x3.config import InitialMemoryConfig
from bball3x3.schemas.agent import AgentOutput, CoordinationConfig
from bball3x3.schemas.memory import CSEntry, MemoryEntry
from bball3x3.schemas.messages import CaptainCall, Message


class CoordinationView(Protocol):
    """Read interface used by the WS3 observation builder (WS4 seam)."""

    def captain_call(self, team: str, event_idx: int) -> CaptainCall | None: ...

    def inbox(self, team: str, pid: str, event_idx: int) -> list[Message]: ...

    def shared_memory(self, team: str, event_idx: int) -> list[MemoryEntry]: ...

    def cs_table(self, team: str, event_idx: int) -> list[CSEntry]: ...


class NullCoordinationView:
    """No-op coordination view returning empty state for all queries."""

    def captain_call(self, team: str, event_idx: int) -> CaptainCall | None:
        _ = (team, event_idx)
        return None

    def inbox(self, team: str, pid: str, event_idx: int) -> list[Message]:
        _ = (team, pid, event_idx)
        return []

    def shared_memory(self, team: str, event_idx: int) -> list[MemoryEntry]:
        _ = (team, event_idx)
        return []

    def cs_table(self, team: str, event_idx: int) -> list[CSEntry]:
        _ = (team, event_idx)
        return []


class StaticCoordinationView:
    """Fixture-backed coordination view for unit tests and prompt harness scenarios."""

    def __init__(
        self,
        *,
        captain_calls: dict[str, CaptainCall | None] | None = None,
        inboxes: dict[str, list[Message]] | None = None,
        team_messages: dict[str, list[Message]] | None = None,
        shared_memories: dict[str, list[MemoryEntry]] | None = None,
        cs_tables: dict[str, list[CSEntry]] | None = None,
    ) -> None:
        self._captain_calls = dict(captain_calls or {})
        self._inboxes = dict(inboxes or {})
        self._team_messages = dict(team_messages or {})
        self._shared_memories = dict(shared_memories or {})
        self._cs_tables = dict(cs_tables or {})

    def captain_call(self, team: str, event_idx: int) -> CaptainCall | None:
        _ = event_idx
        return self._captain_calls.get(team)

    def inbox(self, team: str, pid: str, event_idx: int) -> list[Message]:
        _ = event_idx
        if pid in self._inboxes:
            return [m for m in self._inboxes[pid] if m.sender[:1] == team]
        return [
            m
            for m in self._team_messages.get(team, [])
            if m.sender[:1] == team and m.sender != pid
        ]

    def shared_memory(self, team: str, event_idx: int) -> list[MemoryEntry]:
        _ = event_idx
        return list(self._shared_memories.get(team, []))

    def cs_table(self, team: str, event_idx: int) -> list[CSEntry]:
        _ = event_idx
        return list(self._cs_tables.get(team, []))


def build_initial_memory_entries(
    init_cfg: InitialMemoryConfig | None,
) -> dict[str, list[MemoryEntry]]:
    """Build mirrored initial shared memory entries M01.. from InitialMemoryConfig."""
    if init_cfg is None:
        return {"A": [], "B": []}
    out: dict[str, list[MemoryEntry]] = {"A": [], "B": []}
    for team in ("A", "B"):
        opp_team = "B" if team == "A" else "A"
        for idx, item in enumerate(init_cfg.opponent_scouting, start=1):
            slot_num = item.opponent_slot[1:] if len(item.opponent_slot) > 1 else "1"
            opp_id = f"{opp_team}{slot_num}"
            out[team].append(
                MemoryEntry(
                    id=f"M{idx:02d}",
                    opponent=opp_id,
                    category=item.category,
                    tendency=item.tendency,
                    confidence=1,
                    observed_by="PREGAME",
                    decision_event=0,
                )
            )
    return out


class SimpleCoordinationView:
    """Minimal t -> t+1 coordination store for WS3 (D2), before WS4 replaces it."""

    def __init__(
        self,
        initial_memory: dict[str, list[MemoryEntry]] | None = None,
    ) -> None:
        self._messages_by_event: dict[tuple[str, int], list[Message]] = defaultdict(list)
        self._current_call: dict[str, CaptainCall | None] = {"A": None, "B": None}
        self._call_updated_at: dict[str, int] = {"A": 0, "B": 0}
        self._memory: dict[str, list[MemoryEntry]] = {
            "A": list((initial_memory or {}).get("A", [])),
            "B": list((initial_memory or {}).get("B", [])),
        }
        self._cs: dict[str, list[CSEntry]] = {"A": [], "B": []}

    def captain_call(self, team: str, event_idx: int) -> CaptainCall | None:
        if self._call_updated_at.get(team, 0) < event_idx:
            return self._current_call.get(team)
        return None

    def inbox(self, team: str, pid: str, event_idx: int) -> list[Message]:
        # Deliver messages emitted at event_idx - 1 to teammates on the same team
        emitted = self._messages_by_event.get((team, event_idx - 1), [])
        return [
            m for m in emitted if m.sender[:1] == team and m.sender != pid
        ]

    def shared_memory(self, team: str, event_idx: int) -> list[MemoryEntry]:
        return [
            entry
            for entry in self._memory.get(team, [])
            if entry.decision_event < event_idx
        ]

    def cs_table(self, team: str, event_idx: int) -> list[CSEntry]:
        return [
            entry
            for entry in self._cs.get(team, [])
            if entry.decision_event < event_idx
        ]

    def record_event(
        self,
        event_idx: int,
        kept_outputs: dict[str, AgentOutput],
        coordination: dict[str, CoordinationConfig],
    ) -> tuple[list[dict], list[dict]]:
        """Ingest filtered outputs from event_idx so they become visible at event_idx + 1.

        Returns (memory_writes, cs_writes) dicts for logging.
        """
        memory_writes: list[dict] = []
        cs_writes: list[dict] = []

        for pid, output in sorted(kept_outputs.items()):
            team = pid[:1]
            flags = coordination.get(team, CoordinationConfig())

            # Store ordinary messages (already filtered by apply_flags)
            for msg in output.messages:
                if msg.sender[:1] == team:
                    self._messages_by_event[(team, event_idx)].append(msg)

            # Handle captain call
            if output.captain_call is not None and flags.captain:
                call = output.captain_call
                if call.maintain and self._current_call.get(team) is not None:
                    prev_call = self._current_call[team]
                    assert prev_call is not None
                    self._current_call[team] = prev_call.model_copy(update={"maintain": True})
                elif call.tactic is not None or call.directives:
                    self._current_call[team] = call
                    self._call_updated_at[team] = event_idx
                # Also deliver captain directives via inbox so Team B sees them in teammate messages
                for d_msg in call.directives:
                    if d_msg.sender[:1] == team:
                        self._messages_by_event[(team, event_idx)].append(
                            d_msg.model_copy(update={"is_captain_channel": True})
                        )

            # Handle memory writes (simple append/dedup for WS3 until WS4 lands)
            if output.memory_update is not None and flags.memory_write:
                mu = output.memory_update
                existing = next(
                    (
                        e
                        for e in self._memory[team]
                        if e.opponent == mu.opponent
                        and e.category == mu.category
                        and e.tendency.lower() == mu.tendency.lower()
                    ),
                    None,
                )
                if existing is not None:
                    existing.confidence += 1
                    existing.decision_event = event_idx
                    memory_writes.append(
                        {
                            "team": team,
                            "player": pid,
                            "proposal": mu,
                            "accepted": True,
                            "merged_into": existing.id,
                            "new_id": None,
                            "memory_id": existing.id,
                            "confidence_after": existing.confidence,
                            "visible_at": event_idx + 1,
                        }
                    )
                else:
                    new_id = f"M{len(self._memory[team]) + 1:02d}"
                    entry = MemoryEntry(
                        id=new_id,
                        opponent=mu.opponent,
                        category=mu.category,  # type: ignore[arg-type]
                        tendency=mu.tendency,
                        confidence=1,
                        observed_by=pid,
                        decision_event=event_idx,
                    )
                    self._memory[team].append(entry)
                    memory_writes.append(
                        {
                            "team": team,
                            "player": pid,
                            "proposal": mu,
                            "accepted": True,
                            "merged_into": None,
                            "new_id": new_id,
                            "memory_id": new_id,
                            "confidence_after": 1,
                            "visible_at": event_idx + 1,
                        }
                    )

            # Handle CS writes
            if output.cs_update is not None and flags.memory_write:
                cu = output.cs_update
                existing_cs = next(
                    (
                        c
                        for c in self._cs[team]
                        if c.side == cu.side
                        and c.opponent_strategy.lower() == cu.opponent_strategy.lower()
                    ),
                    None,
                )
                if existing_cs is not None:
                    existing_cs.counter_strategy = cu.counter_strategy
                    existing_cs.decision_event = event_idx
                    cs_writes.append(
                        {
                            "team": team,
                            "player": pid,
                            "proposal": cu,
                            "accepted": True,
                            "key": existing_cs.key,
                            "merged": True,
                            "visible_at": event_idx + 1,
                        }
                    )
                else:
                    new_key = f"{len(self._cs[team]) + 1:02d}"
                    cs_entry = CSEntry(
                        key=new_key,
                        side=cu.side,
                        opponent_strategy=cu.opponent_strategy,
                        counter_strategy=cu.counter_strategy,
                        created_by=pid,
                        decision_event=event_idx,
                        times_referenced=0,
                    )
                    self._cs[team].append(cs_entry)
                    cs_writes.append(
                        {
                            "team": team,
                            "player": pid,
                            "proposal": cu,
                            "accepted": True,
                            "key": new_key,
                            "merged": False,
                            "visible_at": event_idx + 1,
                        }
                    )

        return memory_writes, cs_writes
