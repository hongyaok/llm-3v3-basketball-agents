from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from .actions import ActionType, InvalidReason
from .agent import AgentOutput, CoordinationConfig
from .memory import CSProposal, MemoryProposal
from .messages import Directive
from .referee import RefereeDecision
from .state import GameState

# Shared field types.
Team = Literal["A", "B"]
EventIndex = Annotated[int, Field(strict=True, ge=1)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
NonEmptyStr = Annotated[str, Field(min_length=1)]
ConstraintId = Annotated[int, Field(strict=True, ge=1, le=20)]
GameEndReason = Literal["CLOCK_EXPIRED", "WIN_SCORE", "OT_WIN"]


def require_both_teams(values: dict[Team, int]) -> dict[Team, int]:
    """Team totals must explicitly include both teams, even when zero."""
    if set(values) != {"A", "B"}:
        raise ValueError("Team totals must contain exactly A and B.")
    return values


TeamCounts = Annotated[
    dict[Team, NonNegativeInt],
    AfterValidator(require_both_teams),
]


class LogModel(BaseModel):
    """Reject misspelled fields and non-finite numeric values."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# ---------------------------------------------------------------------------
# Nested payloads used by the main records.
# ---------------------------------------------------------------------------


class PossessionRef(LogModel):
    possession_id: NonEmptyStr
    team: Team


class ScoringEvent(LogModel):
    team: Team
    points: Annotated[int, Field(strict=True, gt=0)]
    source: Literal["FIELD_GOAL", "FREE_THROW"]
    possession_id: NonEmptyStr


class PossessionChange(LogModel):
    from_possession_id: NonEmptyStr
    to_possession_id: NonEmptyStr
    to_team: Team
    reason: NonEmptyStr

    # PERIOD_BOUNDARY represents starting an OT possession, which need not
    # involve the opposing team gaining control.
    kind: Literal["CONTROL_TRANSFER", "PERIOD_BOUNDARY"]

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        if self.from_possession_id == self.to_possession_id:
            raise ValueError("A possession change must create a new ID.")
        return self


class GameTotals(LogModel):
    decisions: NonNegativeInt
    decisions_by_team: TeamCounts
    transitions: NonNegativeInt
    possessions_by_team: TeamCounts

    @model_validator(mode="after")
    def validate_decision_total(self) -> Self:
        if self.decisions != sum(self.decisions_by_team.values()):
            raise ValueError("Decision total must equal the team totals.")
        return self


# ---------------------------------------------------------------------------
# Game lifecycle.
# ---------------------------------------------------------------------------


class GameStartRecord(LogModel):
    record_type: Literal["game_start"] = "game_start"

    # Required explicitly so an unversioned legacy record is not silently
    # interpreted as a version-1 record.
    schema_version: Literal[1]

    game_id: NonEmptyStr
    experiment_id: NonEmptyStr
    replicate_id: NonEmptyStr
    seed: Annotated[int, Field(strict=True)]

    first_possession: Team
    team_conditions: dict[Team, NonEmptyStr]
    matchup: dict[str, Any]
    coordination: dict[Team, CoordinationConfig]
    roster: dict[str, Any]

    config_hash: NonEmptyStr
    config_snapshot: dict[str, Any]
    prompt_hashes: dict[str, str]
    model_slug: NonEmptyStr
    code_commit: str | None

    initial_state: GameState
    initial_possession_id: NonEmptyStr

    @model_validator(mode="after")
    def validate_initial_metadata(self) -> Self:
        if set(self.team_conditions) != {"A", "B"}:
            raise ValueError("team_conditions must contain A and B.")
        if set(self.coordination) != {"A", "B"}:
            raise ValueError("coordination must contain A and B.")
        if self.initial_state.event_idx != 0:
            raise ValueError("The initial state must have event_idx = 0.")
        if self.initial_state.score != {"A": 0, "B": 0}:
            raise ValueError("A complete game must start at 0-0.")
        if self.initial_state.offense != self.first_possession:
            raise ValueError("Initial offense must match first_possession.")
        return self


class GameEndRecord(LogModel):
    record_type: Literal["game_end"] = "game_end"
    last_event_idx: EventIndex
    end_reason: GameEndReason
    final_score: TeamCounts
    ot_flag: bool
    totals: GameTotals
    total_cost_usd: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_transition_total(self) -> Self:
        if self.totals.transitions != self.last_event_idx:
            raise ValueError(
                "Transition total must equal the last contiguous event index."
            )
        return self


# ---------------------------------------------------------------------------
# Player decisions.
# ---------------------------------------------------------------------------


class DecisionRecord(LogModel):
    record_type: Literal["decision"] = "decision"
    event_idx: EventIndex
    player: NonEmptyStr
    team: Team

    raw_output: str
    parsed_output: AgentOutput | None
    parse_ok: bool

    # Required explicitly: null means checked and valid.
    invalid_reason: InvalidReason | None

    remapped_action: ActionType | None = None
    remapped_target: str | None = None

    # These are the actions handed to the resolver, not guaranteed outcomes.
    executed_action: ActionType
    executed_target: str | None

    observation_hash: str = ""
    memory_ref: list[str] | None = None
    latency_ms: float = Field(default=0.0, ge=0)
    tokens: dict[str, NonNegativeInt] = Field(default_factory=dict)
    cost_usd: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_proposal_and_execution(self) -> Self:
        if self.parse_ok:
            if self.parsed_output is None:
                raise ValueError("A successful parse requires parsed_output.")
            if not self.parsed_output.parse_ok:
                raise ValueError("The two parse_ok fields must agree.")
            if self.invalid_reason == "PARSE_FAIL":
                raise ValueError("A successful parse cannot be PARSE_FAIL.")
        else:
            if self.parsed_output is not None:
                raise ValueError("A final parse failure requires null output.")
            if self.invalid_reason != "PARSE_FAIL":
                raise ValueError("A failed parse must use PARSE_FAIL.")

        if self.invalid_reason is None:
            if self.remapped_action is not None or self.remapped_target is not None:
                raise ValueError("A valid proposal must not have a replacement.")

            if self.parsed_output is None:
                raise ValueError("A valid proposal requires parsed_output.")

            proposed = (
                self.parsed_output.action,
                self.parsed_output.target,
            )
            executed = (self.executed_action, self.executed_target)

            if proposed != executed:
                raise ValueError("A valid proposal must execute unchanged.")
        else:
            if self.remapped_action is None:
                raise ValueError("An invalid proposal requires a safe replacement.")

            replacement = (self.remapped_action, self.remapped_target)
            executed = (self.executed_action, self.executed_target)

            if replacement != executed:
                raise ValueError("Executed action must match the replacement.")

        return self


# ---------------------------------------------------------------------------
# Existing coordination records.
# Their detailed metric semantics will be extended in a later WS6 stage.
# ---------------------------------------------------------------------------


class MessageRecord(LogModel):
    record_type: Literal["message"] = "message"
    event_idx: EventIndex
    sender: NonEmptyStr
    team: Team
    channel: Literal["teammate", "captain"]
    kind: Literal["action", "tactic", "info"]
    text: str
    directive: Directive | None = None
    cs: str | None = None
    delivered_at: EventIndex | None = None
    suppressed: bool = False


class CaptainCallRecord(LogModel):
    record_type: Literal["captain_call"] = "captain_call"
    event_idx: EventIndex
    team: Team
    maintain: bool
    tactic: str | None = None
    cs: str | None = None
    directives: list[dict[str, Any]] = Field(default_factory=list)


class MemoryProposalRecord(LogModel):
    record_type: Literal["memory_proposal"] = "memory_proposal"
    event_idx: EventIndex
    team: Team
    player: NonEmptyStr
    proposal: MemoryProposal
    accepted: bool
    merged_into: str | None = None
    new_id: str | None = None
    similarity: float | None = None
    confidence_after: int | None = None


class CSProposalRecord(LogModel):
    record_type: Literal["cs_proposal"] = "cs_proposal"
    event_idx: EventIndex
    team: Team
    player: NonEmptyStr
    proposal: CSProposal
    accepted: bool
    key: str | None = None
    merged: bool = False


# ---------------------------------------------------------------------------
# Engine and referee outcomes.
# ---------------------------------------------------------------------------


class ResolutionRecord(LogModel):
    record_type: Literal["resolution"] = "resolution"
    event_idx: EventIndex

    actions: dict[str, ActionType]
    action_targets: dict[str, str | None]
    outcomes: dict[str, Any] = Field(default_factory=dict)
    model_terms: dict[str, Any] = Field(default_factory=dict)
    rng_draws: dict[str, Any] = Field(default_factory=dict)

    possession_before: PossessionRef
    possession_after: PossessionRef | None
    scoring_events: list[ScoringEvent]
    possession_changes: list[PossessionChange]

    game_over: bool
    game_end_reason: GameEndReason | None

    @model_validator(mode="after")
    def validate_resolution_fields(self) -> Self:
        if self.actions.keys() != self.action_targets.keys():
            raise ValueError("Actions and targets must cover the same players.")

        if self.game_over:
            if self.game_end_reason is None:
                raise ValueError("A finished game requires an end reason.")
            if self.possession_after is not None:
                raise ValueError("A finished game has no active next possession.")
        else:
            if self.game_end_reason is not None:
                raise ValueError("An ongoing game cannot have an end reason.")
            if self.possession_after is None:
                raise ValueError("An ongoing game requires an active possession.")

        return self


class RefereeRecord(LogModel):
    record_type: Literal["referee"] = "referee"
    event_idx: EventIndex
    query: str
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    decision: RefereeDecision
    latency_ms: float = Field(default=0.0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)


class StateRecord(LogModel):
    record_type: Literal["state"] = "state"
    event_idx: EventIndex

    # Use the normal typed state whenever possible.
    state: GameState | None

    # Preserve an invalid candidate snapshot if GameState rejects it.
    raw_state: dict[str, Any] | None = None
    state_validation_errors: list[str] = Field(default_factory=list)

    # Required explicitly so missing checks cannot look like a clean transition.
    invariant_checks_completed: bool
    constraints_checked: list[ConstraintId]

    @model_validator(mode="after")
    def validate_snapshot_and_checks(self) -> Self:
        if (self.state is None) == (self.raw_state is None):
            raise ValueError("Provide exactly one of state or raw_state.")

        if self.state is not None:
            if self.state.event_idx != self.event_idx:
                raise ValueError("State and record event indices must agree.")
            if self.state_validation_errors:
                raise ValueError("A typed state must not have validation errors.")
        else:
            if not self.state_validation_errors:
                raise ValueError("A raw state requires validation error details.")
            if self.raw_state.get("event_idx") != self.event_idx:
                raise ValueError("Raw state and record event indices must agree.")

        checked = set(self.constraints_checked)

        if len(checked) != len(self.constraints_checked):
            raise ValueError("constraints_checked must not contain duplicates.")

        if self.invariant_checks_completed and checked != set(range(1, 21)):
            raise ValueError("Completed checking requires all 20 constraints.")

        return self


class InvariantViolationRecord(LogModel):
    record_type: Literal["invariant_violation"] = "invariant_violation"
    event_idx: EventIndex
    constraint_id: ConstraintId
    constraint_name: NonEmptyStr
    details: NonEmptyStr


class PossessionEndRecord(LogModel):
    record_type: Literal["possession_end"] = "possession_end"
    possession_id: NonEmptyStr
    team: Team
    points: NonNegativeInt
    points_by_team: TeamCounts
    end_reason: NonEmptyStr
    start_event_idx: EventIndex
    end_event_idx: EventIndex

    @model_validator(mode="after")
    def validate_possession_totals(self) -> Self:
        if self.end_event_idx < self.start_event_idx:
            raise ValueError("A possession cannot end before it starts.")
        if self.points != self.points_by_team[self.team]:
            raise ValueError("points must equal the owning team's points.")
        return self


# The reader can use TypeAdapter(LogRecord) to select the correct model
# automatically from each JSON object's record_type.
LogRecord = Annotated[
    GameStartRecord
    | DecisionRecord
    | MessageRecord
    | CaptainCallRecord
    | MemoryProposalRecord
    | CSProposalRecord
    | ResolutionRecord
    | RefereeRecord
    | StateRecord
    | InvariantViolationRecord
    | PossessionEndRecord
    | GameEndRecord,
    Field(discriminator="record_type"),
]