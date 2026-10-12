"""Per-game metrics computed from event-log records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

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

from .log_reader import GameLogIndex, LogRecord, record_event_idx, record_type

Team = Literal["A", "B"]
MetricStatus = Literal[
    "ok",
    "undefined",
    "incomplete",
    "insufficient_evidence",
    "not_applicable",
]
_TEAMS: tuple[Team, Team] = ("A", "B")


@dataclass(frozen=True)
class RateMetric:
    """A numerator and denominator with an explicit evidence status."""

    numerator: int
    denominator: int
    status: MetricStatus = "ok"

    @property
    def rate(self) -> float | None:
        if self.status != "ok" or self.denominator == 0:
            return None
        return self.numerator / self.denominator

    def to_dict(self) -> dict[str, int | float | str | None]:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "rate": self.rate,
            "status": self.status,
        }


def _rate(
    numerator: int,
    denominator: int,
    *,
    complete: bool,
    evidence_complete: bool = True,
    applicable: bool = True,
) -> RateMetric:
    if not applicable:
        status: MetricStatus = "not_applicable"
    elif not complete:
        status = "incomplete"
    elif not evidence_complete:
        status = "insufficient_evidence"
    elif denominator == 0:
        status = "undefined"
    else:
        status = "ok"
    return RateMetric(numerator, denominator, status)


@dataclass
class GameMetrics:
    """Counts and rates for one game, separated by physical team where relevant."""

    game_complete: bool
    team_conditions: dict[str, str]
    ppp: dict[str, RateMetric]
    maar: dict[str, RateMetric]
    ccar: dict[str, RateMetric]
    cssr: dict[str, RateMetric]
    maur: dict[str, RateMetric]
    grounded_maur: dict[str, RateMetric]
    iar: dict[str, RateMetric]
    iar_game: RateMetric
    iar_by_reason: dict[str, dict[str, RateMetric]]
    sir: RateMetric
    sir_by_constraint: dict[str, RateMetric]
    referee_call_rate: RateMetric
    referee_calls_by_type: dict[str, int] = field(default_factory=dict)
    memory_validation_complete: dict[str, bool] = field(default_factory=dict)
    grounding_context_complete: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly summary without discarding denominator status."""

        def team_rates(values: Mapping[str, RateMetric]) -> dict[str, Any]:
            return {team: metric.to_dict() for team, metric in values.items()}

        return {
            "game_complete": self.game_complete,
            "team_conditions": dict(self.team_conditions),
            "ppp": team_rates(self.ppp),
            "maar": team_rates(self.maar),
            "ccar": team_rates(self.ccar),
            "cssr": team_rates(self.cssr),
            "maur": team_rates(self.maur),
            "grounded_maur": team_rates(self.grounded_maur),
            "iar": team_rates(self.iar),
            "iar_game": self.iar_game.to_dict(),
            "iar_by_reason": {
                team: team_rates(metrics) for team, metrics in self.iar_by_reason.items()
            },
            "sir": self.sir.to_dict(),
            "sir_by_constraint": team_rates(self.sir_by_constraint),
            "referee_call_rate": self.referee_call_rate.to_dict(),
            "referee_calls_by_type": dict(self.referee_calls_by_type),
            "memory_validation_complete": dict(self.memory_validation_complete),
            "grounding_context_complete": dict(self.grounding_context_complete),
        }


@dataclass(frozen=True)
class _DirectiveGroup:
    team: Team
    delivery_event: int
    recipient: str
    expected: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class _TacticCall:
    team: Team
    event_idx: int
    cs_key: str | None


def _data(record: LogRecord) -> Mapping[str, Any]:
    if isinstance(record, BaseModel):
        return record.model_dump(mode="python")
    return record


def _nested(value: Any) -> Mapping[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    return value if isinstance(value, Mapping) else {}


def _records(records: GameLogIndex | Iterable[LogRecord]) -> list[LogRecord]:
    return list(records.records if isinstance(records, GameLogIndex) else records)


def _team(value: Any) -> Team | None:
    return value if value in _TEAMS else None


def _game_records(
    records: Sequence[LogRecord],
) -> tuple[GameStartRecord | None, GameEndRecord | None, bool]:
    start = records[0] if records and isinstance(records[0], GameStartRecord) else None
    end = records[-1] if records and isinstance(records[-1], GameEndRecord) else None
    return start, end, end is not None


def _feature_enabled(start: GameStartRecord | None, team: Team, feature: str) -> bool:
    if start is None:
        return True
    return bool(getattr(start.coordination[team], feature))


def _decision_map(
    records: Sequence[LogRecord],
) -> tuple[dict[tuple[int, str], DecisionRecord], dict[Team, list[DecisionRecord]]]:
    by_key: dict[tuple[int, str], DecisionRecord] = {}
    by_team: dict[Team, list[DecisionRecord]] = {team: [] for team in _TEAMS}
    for record in records:
        if not isinstance(record, DecisionRecord):
            continue
        by_key[(record.event_idx, record.player)] = record
        by_team[record.team].append(record)
    return by_key, by_team


def _directive_groups(records: Sequence[LogRecord], channel: str) -> list[_DirectiveGroup]:
    grouped: defaultdict[tuple[Team, int, str], list[tuple[str, str | None]]] = defaultdict(list)
    captain_messages: defaultdict[
        tuple[int, Team], dict[str, list[tuple[str, str | None]]]
    ] = defaultdict(lambda: defaultdict(list))

    for record in records:
        if not isinstance(record, MessageRecord):
            continue
        if record.channel != channel or record.suppressed or record.directive is None:
            continue
        delivery_event = record.delivered_at or record.event_idx + 1
        key = (record.team, delivery_event, record.directive.to)
        grouped[key].append((record.directive.act.upper(), record.directive.target))
        if channel == "captain":
            captain_messages[(record.event_idx, record.team)][record.directive.to].append(
                (record.directive.act.upper(), record.directive.target)
            )

    if channel == "captain":
        current: dict[Team, dict[str, list[tuple[str, str | None]]]] = {
            team: {} for team in _TEAMS
        }
        calls = sorted(
            (record for record in records if isinstance(record, CaptainCallRecord)),
            key=lambda record: record.event_idx,
        )
        for record in calls:
            message_directives = captain_messages.get((record.event_idx, record.team))
            parsed: defaultdict[str, list[tuple[str, str | None]]] = defaultdict(list)
            for raw in record.directives:
                entry = _nested(raw)
                directive = _nested(entry.get("directive")) or entry
                recipient = directive.get("to")
                action = directive.get("act")
                target = directive.get("target")
                if isinstance(recipient, str) and isinstance(action, str):
                    parsed[recipient].append(
                        (action.upper(), target if isinstance(target, str) else None)
                    )
            if message_directives:
                current[record.team] = dict(message_directives)
            elif not record.maintain:
                current[record.team] = dict(parsed)

            if not message_directives:
                for recipient, expected in current[record.team].items():
                    grouped[(record.team, record.event_idx + 1, recipient)].extend(expected)

    return [
        _DirectiveGroup(team, delivery, recipient, tuple(expected))
        for (team, delivery, recipient), expected in grouped.items()
    ]


def _instruction_adherence(
    records: Sequence[LogRecord],
    channel: str,
    window: int,
    complete: bool,
    start: GameStartRecord | None,
    decision_evidence: Mapping[Team, bool],
) -> dict[str, RateMetric]:
    decisions, _ = _decision_map(records)
    matched: defaultdict[Team, int] = defaultdict(int)
    addressed: defaultdict[Team, int] = defaultdict(int)

    for group in _directive_groups(records, channel):
        responses = [
            decisions[(event_idx, group.recipient)]
            for event_idx in range(group.delivery_event, group.delivery_event + window)
            if (event_idx, group.recipient) in decisions
        ]
        if not responses:
            continue
        addressed[group.team] += 1
        if any(
            response.parsed_output is not None
            and any(
                response.parsed_output.action.upper() == action
                and (target is None or response.parsed_output.target == target)
                for action, target in group.expected
            )
            for response in responses
        ):
            matched[group.team] += 1

    feature = "comms" if channel == "teammate" else "captain"
    return {
        team: _rate(
            matched[team],
            addressed[team],
            complete=complete,
            evidence_complete=decision_evidence[team],
            applicable=_feature_enabled(start, team, feature),
        )
        for team in _TEAMS
    }


def _tactic_calls(records: Sequence[LogRecord]) -> list[_TacticCall]:
    calls: list[_TacticCall] = []
    captain_message_groups: set[tuple[int, Team]] = set()
    for record in records:
        if not isinstance(record, MessageRecord):
            continue
        if record.kind != "tactic" or record.suppressed:
            continue
        calls.append(_TacticCall(record.team, record.event_idx, record.cs))
        if record.channel == "captain":
            captain_message_groups.add((record.event_idx, record.team))

    for record in records:
        if not isinstance(record, CaptainCallRecord):
            continue
        if (record.event_idx, record.team) in captain_message_groups:
            continue
        if record.tactic is not None:
            calls.append(_TacticCall(record.team, record.event_idx, record.cs))
    return calls


def _visible_at(data: Mapping[str, Any], event_idx: int) -> int:
    value = data.get("visible_at", data.get("delivered_at"))
    return value if isinstance(value, int) and not isinstance(value, bool) else event_idx + 1


def _cs_availability(records: Sequence[LogRecord]) -> dict[Team, dict[str, int]]:
    available: dict[Team, dict[str, int]] = {team: {} for team in _TEAMS}
    for record in records:
        if isinstance(record, CSProposalRecord):
            if record.accepted and record.key:
                available[record.team].setdefault(record.key, record.event_idx + 1)
            continue
        if record_type(record) != "cs_write":
            continue
        data = _data(record)
        team = _team(data.get("team"))
        key = data.get("key")
        event_idx = record_event_idx(record)
        if team is not None and isinstance(key, str) and key and event_idx is not None:
            available[team].setdefault(key, _visible_at(data, event_idx))
    return available


def _cssr(
    records: Sequence[LogRecord],
    complete: bool,
    start: GameStartRecord | None,
) -> dict[str, RateMetric]:
    availability = _cs_availability(records)
    valid: defaultdict[Team, int] = defaultdict(int)
    total: defaultdict[Team, int] = defaultdict(int)
    for call in _tactic_calls(records):
        total[call.team] += 1
        if call.cs_key is not None:
            visible_at = availability[call.team].get(call.cs_key)
            if visible_at is not None and visible_at <= call.event_idx:
                valid[call.team] += 1
    return {
        team: _rate(
            valid[team],
            total[team],
            complete=complete,
            applicable=_feature_enabled(start, team, "captain"),
        )
        for team in _TEAMS
    }


def _normalise_initial_memory(
    known_memory_ids: Mapping[str, Iterable[str]] | None,
    memory_opponents: Mapping[str, Mapping[str, str]] | None,
) -> tuple[
    dict[Team, dict[str, int]],
    dict[Team, dict[str, int]],
    dict[Team, dict[str, str]],
    dict[Team, bool],
]:
    availability: dict[Team, dict[str, int]] = {team: {} for team in _TEAMS}
    unavailable_from: dict[Team, dict[str, int]] = {team: {} for team in _TEAMS}
    opponents: dict[Team, dict[str, str]] = {team: {} for team in _TEAMS}
    complete = {team: known_memory_ids is not None and team in known_memory_ids for team in _TEAMS}

    if known_memory_ids is not None:
        for team in _TEAMS:
            for memory_id in known_memory_ids.get(team, ()):
                if isinstance(memory_id, str) and memory_id:
                    availability[team][memory_id] = 0
    if memory_opponents is not None:
        for team in _TEAMS:
            for memory_id, opponent in memory_opponents.get(team, {}).items():
                if isinstance(memory_id, str) and isinstance(opponent, str):
                    opponents[team][memory_id] = opponent
    return availability, unavailable_from, opponents, complete


def _add_memory_writes(
    records: Sequence[LogRecord],
    availability: dict[Team, dict[str, int]],
    unavailable_from: dict[Team, dict[str, int]],
    opponents: dict[Team, dict[str, str]],
) -> None:
    for record in records:
        if isinstance(record, MemoryProposalRecord):
            if not record.accepted:
                continue
            memory_ids = [value for value in (record.new_id, record.merged_into) if value]
            for memory_id in memory_ids:
                availability[record.team].setdefault(memory_id, record.event_idx + 1)
                opponents[record.team][memory_id] = record.proposal.opponent
            continue
        if record_type(record) != "memory_write":
            continue
        data = _data(record)
        team = _team(data.get("team"))
        event_idx = record_event_idx(record)
        memory_id = data.get("id", data.get("memory_id"))
        opponent = data.get("opponent")
        if team is None or event_idx is None or not isinstance(memory_id, str) or not memory_id:
            continue
        availability[team].setdefault(memory_id, _visible_at(data, event_idx))
        if isinstance(opponent, str):
            opponents[team][memory_id] = opponent
        evicted = data.get("evicted_ids", data.get("evicted_id", ()))
        if isinstance(evicted, str):
            evicted = (evicted,)
        if isinstance(evicted, (list, tuple, set)):
            for evicted_id in evicted:
                if isinstance(evicted_id, str) and evicted_id:
                    unavailable_from[team][evicted_id] = _visible_at(data, event_idx)


def _explicit_involved_opponents(
    decision: DecisionRecord,
    resolution: ResolutionRecord | None,
) -> tuple[set[str], bool]:
    involved: set[str] = set()
    own_team = decision.team
    target = decision.parsed_output.target if decision.parsed_output is not None else None
    if isinstance(target, str) and target[:1] in _TEAMS and target[:1] != own_team:
        involved.add(target)

    if resolution is None:
        return involved, False
    player_outcome = resolution.outcomes.get(decision.player)
    if not isinstance(player_outcome, Mapping):
        return involved, False
    explicit = player_outcome.get("involved_opponents")
    if not isinstance(explicit, (list, tuple, set)):
        return involved, False
    involved.update(
        value
        for value in explicit
        if isinstance(value, str) and value[:1] in _TEAMS and value[:1] != own_team
    )
    return involved, True


def _memory_metrics(
    records: Sequence[LogRecord],
    decisions_by_team: Mapping[Team, Sequence[DecisionRecord]],
    complete: bool,
    decision_evidence: Mapping[Team, bool],
    known_memory_ids: Mapping[str, Iterable[str]] | None,
    memory_opponents: Mapping[str, Mapping[str, str]] | None,
) -> tuple[dict[str, RateMetric], dict[str, RateMetric], dict[str, bool], dict[str, bool]]:
    availability, unavailable_from, opponents, validation_complete = (
        _normalise_initial_memory(known_memory_ids, memory_opponents)
    )
    _add_memory_writes(records, availability, unavailable_from, opponents)
    resolutions = {
        record.event_idx: record for record in records if isinstance(record, ResolutionRecord)
    }
    used: defaultdict[Team, int] = defaultdict(int)
    grounded: defaultdict[Team, int] = defaultdict(int)
    grounding_complete = {
        team: validation_complete[team]
        and memory_opponents is not None
        and team in memory_opponents
        for team in _TEAMS
    }

    for team in _TEAMS:
        for decision in decisions_by_team[team]:
            refs = decision.memory_ref
            if refs is None and decision.parsed_output is not None:
                refs = decision.parsed_output.memory_ref
            valid_refs = [
                ref
                for ref in refs or ()
                if ref in availability[team]
                and availability[team][ref] <= decision.event_idx
                and (
                    ref not in unavailable_from[team]
                    or decision.event_idx < unavailable_from[team][ref]
                )
            ]
            if not valid_refs:
                continue
            used[team] += 1
            involved, involvement_complete = _explicit_involved_opponents(
                decision, resolutions.get(decision.event_idx)
            )
            if any(opponents[team].get(ref) in involved for ref in valid_refs):
                grounded[team] += 1
            elif not involvement_complete:
                grounding_complete[team] = False

    maur = {
        team: _rate(
            used[team],
            len(decisions_by_team[team]),
            complete=complete,
            evidence_complete=validation_complete[team] and decision_evidence[team],
        )
        for team in _TEAMS
    }
    grounded_maur = {
        team: _rate(
            grounded[team],
            len(decisions_by_team[team]),
            complete=complete,
            evidence_complete=grounding_complete[team] and decision_evidence[team],
        )
        for team in _TEAMS
    }
    return maur, grounded_maur, validation_complete, grounding_complete


def compute_game_metrics(
    records: GameLogIndex | Iterable[LogRecord],
    *,
    window: int = 1,
    known_memory_ids: Mapping[str, Iterable[str]] | None = None,
    memory_opponents: Mapping[str, Mapping[str, str]] | None = None,
) -> GameMetrics:
    """Compute per-team coordination/adaptation metrics and game validity metrics.

    ``window=1`` checks the decision at message delivery. ``window=2`` counts
    an addressed opportunity as aligned when either of the next two decisions
    matches at least one directive. Initial memory inputs must be team-scoped,
    for example ``{"A": {"M01"}, "B": {"M01"}}``.
    """
    if window not in (1, 2):
        raise ValueError("window must be 1 or 2")
    items = _records(records)
    start, end, complete = _game_records(items)
    team_conditions = dict(start.team_conditions) if start is not None else {}
    _, decisions_by_team = _decision_map(items)
    decision_evidence = {
        team: end is not None
        and len(decisions_by_team[team]) == end.totals.decisions_by_team[team]
        for team in _TEAMS
    }

    points: defaultdict[Team, int] = defaultdict(int)
    possessions: defaultdict[Team, int] = defaultdict(int)
    for record in items:
        if not isinstance(record, PossessionEndRecord):
            continue
        possessions[record.team] += 1
        for team in _TEAMS:
            points[team] += record.points_by_team[team]
    ppp = {}
    for team in _TEAMS:
        evidence = end is not None
        if end is not None:
            evidence = (
                points[team] == end.final_score[team]
                and possessions[team] == end.totals.possessions_by_team[team]
            )
        ppp[team] = _rate(
            points[team], possessions[team], complete=complete, evidence_complete=evidence
        )

    maar = _instruction_adherence(
        items, "teammate", window, complete, start, decision_evidence
    )
    ccar = _instruction_adherence(
        items, "captain", window, complete, start, decision_evidence
    )
    cssr = _cssr(items, complete, start)
    maur, grounded_maur, memory_complete, grounding_complete = _memory_metrics(
        items,
        decisions_by_team,
        complete,
        decision_evidence,
        known_memory_ids,
        memory_opponents,
    )

    invalid_counts: defaultdict[Team, int] = defaultdict(int)
    invalid_by_reason: dict[Team, defaultdict[str, int]] = {
        team: defaultdict(int) for team in _TEAMS
    }
    for team in _TEAMS:
        for decision in decisions_by_team[team]:
            if decision.invalid_reason is not None:
                invalid_counts[team] += 1
                invalid_by_reason[team][decision.invalid_reason] += 1
    iar = {
        team: _rate(
            invalid_counts[team],
            len(decisions_by_team[team]),
            complete=complete,
            evidence_complete=decision_evidence[team],
        )
        for team in _TEAMS
    }
    total_decisions = sum(len(decisions_by_team[team]) for team in _TEAMS)
    total_invalid = sum(invalid_counts.values())
    iar_game = _rate(
        total_invalid,
        total_decisions,
        complete=complete,
        evidence_complete=end is not None and total_decisions == end.totals.decisions,
    )
    iar_by_reason = {
        team: {
            reason: _rate(
                count,
                len(decisions_by_team[team]),
                complete=complete,
                evidence_complete=decision_evidence[team],
            )
            for reason, count in sorted(invalid_by_reason[team].items())
        }
        for team in _TEAMS
    }

    state_records = [record for record in items if isinstance(record, StateRecord)]
    states = {record.event_idx: record for record in state_records}
    violations: defaultdict[str, set[int]] = defaultdict(set)
    violated_events: set[int] = set()
    violation_events_valid = True
    for record in items:
        if not isinstance(record, InvariantViolationRecord):
            continue
        if record.event_idx not in states:
            violation_events_valid = False
            continue
        violated_events.add(record.event_idx)
        violations[record.constraint_name].add(record.event_idx)

    expected_events = set(range(1, end.last_event_idx + 1)) if end is not None else set(states)
    sir_evidence = (
        end is not None
        and set(states) == expected_events
        and len(states) == len(state_records)
        and violation_events_valid
        and all(
            state.invariant_checks_completed and set(state.constraints_checked) == set(range(1, 21))
            for state in states.values()
        )
    )
    sir = _rate(
        len(violated_events), len(states), complete=complete, evidence_complete=sir_evidence
    )
    sir_by_constraint = {
        name: _rate(len(events), len(states), complete=complete, evidence_complete=sir_evidence)
        for name, events in sorted(violations.items())
    }

    referee_by_event: defaultdict[int, list[RefereeRecord]] = defaultdict(list)
    calls_by_type: defaultdict[str, int] = defaultdict(int)
    for record in items:
        if isinstance(record, RefereeRecord):
            referee_by_event[record.event_idx].append(record)
            if record.decision.call != "NONE":
                calls_by_type[record.decision.call] += 1
    referee_evidence = (
        end is not None
        and set(referee_by_event) == expected_events
        and all(len(records_at_event) == 1 for records_at_event in referee_by_event.values())
    )
    referee_call_rate = _rate(
        sum(calls_by_type.values()),
        len(states),
        complete=complete,
        evidence_complete=referee_evidence,
    )

    return GameMetrics(
        game_complete=complete,
        team_conditions=team_conditions,
        ppp=ppp,
        maar=maar,
        ccar=ccar,
        cssr=cssr,
        maur=maur,
        grounded_maur=grounded_maur,
        iar=iar,
        iar_game=iar_game,
        iar_by_reason=iar_by_reason,
        sir=sir,
        sir_by_constraint=sir_by_constraint,
        referee_call_rate=referee_call_rate,
        referee_calls_by_type=dict(sorted(calls_by_type.items())),
        memory_validation_complete=memory_complete,
        grounding_context_complete=grounding_complete,
    )
