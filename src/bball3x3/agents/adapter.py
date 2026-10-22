"""Adapter between LLM DecisionResult, engine ActionProposal, and WS6 DecisionRecord (WS3 §3.5)."""

from __future__ import annotations

from bball3x3.agents.llm_player import PARSE_FAIL_PLACEHOLDER, DecisionResult
from bball3x3.engine.actions import remap_invalid_action
from bball3x3.schemas.actions import ActionProposal, RemappedAction
from bball3x3.schemas.log import DecisionRecord
from bball3x3.schemas.state import GameState


def decision_to_proposal(player_id: str, result: DecisionResult) -> ActionProposal:
    """Convert a DecisionResult into an ActionProposal for EngineSession.step()."""
    if not result.kept.parse_ok:
        return ActionProposal(
            player_id=player_id,
            action=PARSE_FAIL_PLACEHOLDER,
            target=None,
            memory_ref=None,
        )
    return ActionProposal(
        player_id=player_id,
        action=result.kept.action,
        target=result.kept.target,
        memory_ref=result.kept.memory_ref,
    )


def legalize_decision(
    state: GameState,
    player_id: str,
    result: DecisionResult,
) -> tuple[ActionProposal, RemappedAction | None]:
    """Run remap_invalid_action on a DecisionResult, ensuring PARSE_FAIL reason on parse failure."""
    raw_proposal = decision_to_proposal(player_id, result)
    fixed, record = remap_invalid_action(state, raw_proposal)
    if not result.kept.parse_ok and record is not None and record.reason != "PARSE_FAIL":
        record = record.model_copy(update={"reason": "PARSE_FAIL"})
    return fixed, record


def build_decision_record(
    *,
    event_idx: int,
    player_id: str,
    result: DecisionResult,
    fixed: ActionProposal,
    remap: RemappedAction | None,
) -> DecisionRecord:
    """Assemble a validated WS6 DecisionRecord from a DecisionResult and engine legality outcome."""
    team = player_id[:1].upper()
    raw_out = result.raw_attempts[-1] if result.raw_attempts else result.kept.raw_text
    tokens = {
        "prompt": result.prompt_tokens,
        "completion": result.completion_tokens,
        "total": result.total_tokens,
    }
    exec_act = fixed.action.upper()
    exec_target = fixed.target

    if not result.kept.parse_ok:
        return DecisionRecord(
            event_idx=event_idx,
            player=player_id,
            team=team,  # type: ignore[arg-type]
            raw_output=raw_out,
            parsed_output=None,
            parse_ok=False,
            invalid_reason="PARSE_FAIL",
            remapped_action=exec_act,  # type: ignore[arg-type]
            remapped_target=exec_target,
            executed_action=exec_act,  # type: ignore[arg-type]
            executed_target=exec_target,
            observation_text=result.observation_text,
            memory_ref=None,
            latency_ms=result.latency_ms,
            tokens=tokens,
            cost_usd=result.cost_usd,
        )

    # Ensure parsed_output target agrees with normalized executed_target when valid
    parsed_for_log = result.kept
    if remap is None and parsed_for_log.target != exec_target:
        parsed_for_log = parsed_for_log.model_copy(update={"target": exec_target})

    if remap is None:
        return DecisionRecord(
            event_idx=event_idx,
            player=player_id,
            team=team,  # type: ignore[arg-type]
            raw_output=raw_out,
            parsed_output=parsed_for_log,
            parse_ok=True,
            invalid_reason=None,
            remapped_action=None,
            remapped_target=None,
            executed_action=exec_act,  # type: ignore[arg-type]
            executed_target=exec_target,
            observation_text=result.observation_text,
            memory_ref=parsed_for_log.memory_ref,
            latency_ms=result.latency_ms,
            tokens=tokens,
            cost_usd=result.cost_usd,
        )

    return DecisionRecord(
        event_idx=event_idx,
        player=player_id,
        team=team,  # type: ignore[arg-type]
        raw_output=raw_out,
        parsed_output=parsed_for_log,
        parse_ok=True,
        invalid_reason=remap.reason,
        remapped_action=exec_act,  # type: ignore[arg-type]
        remapped_target=exec_target,
        executed_action=exec_act,  # type: ignore[arg-type]
        executed_target=exec_target,
        observation_text=result.observation_text,
        memory_ref=parsed_for_log.memory_ref,
        latency_ms=result.latency_ms,
        tokens=tokens,
        cost_usd=result.cost_usd,
    )
