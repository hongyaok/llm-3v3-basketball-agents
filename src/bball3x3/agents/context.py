"""CoordinationView protocol and WS3 implementations (WS3 §3.2 & §3.6)."""

from __future__ import annotations

from typing import Protocol

from bball3x3.config import InitialMemoryConfig
from bball3x3.coordination.captain import CaptainStore
from bball3x3.coordination.channels import CommsChannel
from bball3x3.memory.counter_strategy import CounterStrategyStore
from bball3x3.memory.shared import SharedMemoryStore
from bball3x3.memory.similarity import Embedder
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
        *,
        captains: dict[str, str] | None = None,
        active_players: set[str] | None = None,
        embedder: Embedder | None = None,
        similarity_threshold: float = 0.80,
    ) -> None:
        self._captain_ids = (
            dict(captains) if captains is not None
            else {"A": "A1", "B": "B1"}
        )
        self._channels = {
            team: CommsChannel(team) for team in ("A", "B")
        }
        self._captain_stores = {
            team: CaptainStore() for team in ("A", "B")
        }
        players = (
            set(active_players)
            if active_players is not None
            else {"A1", "A2", "A3", "B1", "B2", "B3"}
        )
        self._memory_stores = {
            team: SharedMemoryStore(
                opponents={
                    pid for pid in players if pid[:1] != team
                },
                initial_entries=(initial_memory or {}).get(team, []),
                embedder=embedder,
                similarity_threshold=similarity_threshold,
            )
            for team in ("A", "B")
        }
        self._memory_history: dict[
            str, list[tuple[int, list[MemoryEntry]]]
        ] = {
            team: [(0, self._memory_stores[team].entries())]
            for team in ("A", "B")
        }
        self._cs_stores = {
            team: CounterStrategyStore(
                embedder=embedder,
                similarity_threshold=similarity_threshold,
            )
            for team in ("A", "B")
        }
        self._cs_history: dict[
            str, list[tuple[int, list[CSEntry]]]
        ] = {
            team: [(0, [])]
            for team in ("A", "B")
        }

    def captain_call(self, team: str, event_idx: int) -> CaptainCall | None:
        return self._captain_stores[team].current(event_idx)

    def inbox(self, team: str, pid: str, event_idx: int) -> list[Message]:
        if pid[:1] != team:
            return []
        return self._channels[team].deliver(event_idx, pid)

    def shared_memory(self, team: str, event_idx: int) -> list[MemoryEntry]:
        for written_at, entries in reversed(self._memory_history[team]):
            if written_at < event_idx:
                return [entry.model_copy(deep=True) for entry in entries]
        return []

    def cs_table(self, team: str, event_idx: int) -> list[CSEntry]:
        for written_at, entries in reversed(self._cs_history[team]):
            if written_at < event_idx:
                return [entry.model_copy(deep=True) for entry in entries]
        return []

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
            # Validate references against the table visible at decision time.
            visible_cs_keys = {
                entry.key for entry in self.cs_table(team, event_idx)
            }
            tactic_messages = []

            if flags.comms:
                tactic_messages.extend(
                    message
                    for message in output.messages
                    if message.sender == pid and message.kind == "tactic"
                )

            if (
                flags.captain
                and pid == self._captain_ids[team]
                and output.captain_call is not None
                and not output.captain_call.maintain
            ):
                tactic = output.captain_call.tactic
                if (
                    tactic is not None
                    and tactic.sender == pid
                    and tactic.kind == "tactic"
                ):
                    tactic_messages.append(tactic)

            for message in tactic_messages:
                if message.cs in visible_cs_keys:
                    self._cs_stores[team].reference(message.cs)
            # Accept ordinary messages only from their actual author.
            if flags.comms:
                ordinary_messages = [
                    message.model_copy(
                        deep=True,
                        update={"is_captain_channel": False},
                    )
                    for message in output.messages
                    if message.sender == pid
                ]
                self._channels[team].post(event_idx, ordinary_messages)

            # Only the configured captain may submit captain calls.
            if (
                flags.captain
                and pid == self._captain_ids[team]
                and output.captain_call is not None
            ):
                call = output.captain_call.model_copy(deep=True)

                if call.tactic is not None and call.tactic.sender != pid:
                    call.tactic = None

                call.directives = [
                    message
                    for message in call.directives
                    if message.sender == pid
                ]

                self._captain_stores[team].post(event_idx, call)

                # Captain directives still reach teammates with comms off.
                if not call.maintain:
                    captain_messages = [
                        message.model_copy(
                            deep=True,
                            update={"is_captain_channel": True},
                        )
                        for message in call.directives
                    ]
                    self._channels[team].post(event_idx, captain_messages)
            if output.memory_update is not None and flags.memory_write:
                proposal = output.memory_update
                result = {
                    "team": team,
                    "player": pid,
                    "proposal": proposal,
                    "accepted": False,
                    "merged_into": None,
                    "new_id": None,
                    "confidence_after": None,
                }

                try:
                    entry, merged, evicted_ids = (
                        self._memory_stores[team].write(
                            proposal,
                            player_id=pid,
                            event_idx=event_idx,
                        )
                    )
                except ValueError:
                    # Invalid proposals and capacity rejections are logged.
                    memory_writes.append(result)
                else:
                    result.update({
                        "accepted": True,
                        "merged_into": entry.id if merged else None,
                        "new_id": None if merged else entry.id,
                        "memory_id": entry.id,
                        "confidence_after": entry.confidence,
                        "visible_at": event_idx + 1,
                        "evicted_ids": evicted_ids,
                        "entry": entry,
                    })
                    memory_writes.append(result)
                # Validate and store counter-strategy proposals.
            if output.cs_update is not None and flags.memory_write:
                proposal = output.cs_update
                result = {
                    "team": team,
                    "player": pid,
                    "proposal": proposal,
                    "accepted": False,
                    "key": None,
                    "merged": False,
                }

                try:
                    entry, merged = self._cs_stores[team].write(
                        proposal,
                        player_id=pid,
                        event_idx=event_idx,
                    )
                except ValueError:
                    cs_writes.append(result)
                else:
                    result.update({
                        "accepted": True,
                        "key": entry.key,
                        "merged": merged,
                        "visible_at": event_idx + 1,
                        "entry": entry,
                    })
                    cs_writes.append(result)
        # Snapshot after all players' submissions have been processed.
        for team in ("A", "B"):
            self._memory_history[team].append(
                (event_idx, self._memory_stores[team].entries())
            )
            self._cs_history[team].append(
                (event_idx, self._cs_stores[team].entries())
            )

        return memory_writes, cs_writes
