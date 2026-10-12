"""Read and index per-game JSONL event logs.

Known record types are validated against ``schemas.log``. Unknown record types
are retained as dictionaries so logs containing newer records such as
``memory_write`` and ``cs_write`` remain inspectable.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn, TypeAlias

from pydantic import BaseModel, ValidationError

from bball3x3.logging.event_log import LogReadError
from bball3x3.schemas.log import (
    CaptainCallRecord,
    CSProposalRecord,
    DecisionRecord,
    GameEndRecord,
    GameStartRecord,
    InvariantViolationRecord,
    MemoryProposalRecord,
    MessageRecord,
    PossessionEndRecord,
    RefereeRecord,
    ResolutionRecord,
    StateRecord,
)

LogRecord: TypeAlias = BaseModel | dict[str, Any]

_RECORD_MODELS: dict[str, type[BaseModel]] = {
    "game_start": GameStartRecord,
    "decision": DecisionRecord,
    "message": MessageRecord,
    "captain_call": CaptainCallRecord,
    "memory_proposal": MemoryProposalRecord,
    "cs_proposal": CSProposalRecord,
    "resolution": ResolutionRecord,
    "referee": RefereeRecord,
    "state": StateRecord,
    "invariant_violation": InvariantViolationRecord,
    "possession_end": PossessionEndRecord,
    "game_end": GameEndRecord,
}


def _record_mapping(record: LogRecord) -> Mapping[str, Any]:
    if isinstance(record, BaseModel):
        return record.model_dump(mode="python")
    return record


def record_type(record: LogRecord) -> str:
    """Return the discriminator for a typed or forward-compatible record."""
    value = _record_mapping(record).get("record_type")
    if not isinstance(value, str) or not value:
        raise ValueError("log record must have a non-empty string 'record_type'")
    return value


def record_event_idx(record: LogRecord) -> int | None:
    """Return the event described by a record, when it has one."""
    data = _record_mapping(record)
    event_idx = data.get("event_idx")
    if event_idx is None and data.get("record_type") == "possession_end":
        event_idx = data.get("end_event_idx")
    if event_idx is None:
        return None
    if isinstance(event_idx, bool) or not isinstance(event_idx, int) or event_idx < 1:
        raise ValueError(f"event index must be a positive integer, got {event_idx!r}")
    return event_idx


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"JSON number {value!r} exceeds the finite float range")
    return number


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _parse_record(value: Any, source: Path, line_number: int) -> LogRecord:
    if not isinstance(value, dict):
        raise LogReadError(source, line_number, "Each JSONL record must be a JSON object.")

    kind = value.get("record_type")
    if not isinstance(kind, str) or not kind:
        raise LogReadError(source, line_number, "Missing non-empty string 'record_type'.")

    model = _RECORD_MODELS.get(kind)
    if model is None:
        record: LogRecord = value
    else:
        try:
            record = model.model_validate(value)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise LogReadError(
                source, line_number, f"Invalid {kind!r} record ({details})."
            ) from exc

    try:
        record_event_idx(record)
    except ValueError as exc:
        raise LogReadError(source, line_number, str(exc)) from exc
    return record


def iter_jsonl_records(path: str | Path) -> Iterator[LogRecord]:
    """Yield a valid complete game or valid unfinished prefix in file order.

    Unknown record types are preserved as dictionaries. JSON syntax, UTF-8,
    duplicate-key, finite-number, schema and game-boundary errors include the
    source path and one-based line number. A missing ``game_end`` is allowed;
    an empty file is not a game prefix.
    """
    source = Path(path)
    started = False
    ended = False
    line_number = 0

    with source.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            try:
                value = json.loads(
                    raw_line.decode("utf-8"),
                    parse_constant=_reject_constant,
                    parse_float=_finite_float,
                    object_pairs_hook=_unique_object,
                )
            except (UnicodeDecodeError, ValueError) as exc:
                raise LogReadError(source, line_number, str(exc)) from exc

            record = _parse_record(value, source, line_number)
            if ended:
                raise LogReadError(source, line_number, "No records are allowed after game_end.")
            if not started and not isinstance(record, GameStartRecord):
                raise LogReadError(source, line_number, "The first record must be game_start.")
            if started and isinstance(record, GameStartRecord):
                raise LogReadError(source, line_number, "Only one game_start is allowed per file.")

            started = True
            ended = isinstance(record, GameEndRecord)
            yield record

    if not started:
        raise LogReadError(source, max(1, line_number), "Empty log; game_start is missing.")


@dataclass
class GameLogIndex:
    """In-memory indexes over one game's records, preserving file order."""

    records: list[LogRecord]
    source: str | None = None
    by_type: dict[str, list[LogRecord]] = field(init=False)
    by_event: dict[int, list[LogRecord]] = field(init=False)

    def __post_init__(self) -> None:
        type_index: defaultdict[str, list[LogRecord]] = defaultdict(list)
        event_index: defaultdict[int, list[LogRecord]] = defaultdict(list)
        for record in self.records:
            type_index[record_type(record)].append(record)
            event_idx = record_event_idx(record)
            if event_idx is not None:
                event_index[event_idx].append(record)
        self.by_type = dict(type_index)
        self.by_event = dict(event_index)

    @classmethod
    def from_records(
        cls,
        records: Iterable[LogRecord],
        *,
        source: str | None = None,
    ) -> GameLogIndex:
        """Build indexes over already parsed records."""
        return cls(list(records), source=source)

    def records_of_type(self, kind: str) -> tuple[LogRecord, ...]:
        """Return records of one type in file order."""
        return tuple(self.by_type.get(kind, ()))

    def records_at_event(self, event_idx: int) -> tuple[LogRecord, ...]:
        """Return records associated with an event in file order."""
        return tuple(self.by_event.get(event_idx, ()))

    def events(self) -> Iterator[tuple[int, tuple[LogRecord, ...]]]:
        """Iterate event groups in ascending event order."""
        for event_idx in sorted(self.by_event):
            yield event_idx, tuple(self.by_event[event_idx])

    @property
    def game_start(self) -> GameStartRecord | None:
        records = self.records_of_type("game_start")
        record = records[0] if records else None
        return record if isinstance(record, GameStartRecord) else None

    @property
    def game_end(self) -> GameEndRecord | None:
        record = self.records[-1] if self.records else None
        return record if isinstance(record, GameEndRecord) else None

    @property
    def is_complete(self) -> bool:
        """Whether the final record is ``game_end``."""
        return self.game_end is not None


def read_game_log(path: str | Path) -> GameLogIndex:
    """Read a JSONL game log and build type and event indexes."""
    source = Path(path)
    return GameLogIndex.from_records(iter_jsonl_records(source), source=str(source))
