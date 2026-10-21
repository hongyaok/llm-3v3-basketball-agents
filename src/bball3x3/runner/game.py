"""Logged game runner (WS7 v0): heuristic games with automatic WS6 event logging.

The runner owns one JSONL file per game and writes records in the order the
WS6 log contract defines: game_start, then per event six decisions, referee,
resolution, invariant violations, state, and any closed possession ends, with
game_end as the final line on a normal finish. The engine stays the source of
truth; this module only observes the loop hook and assembles records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bball3x3.agents.base import BasePlayer
from bball3x3.analysis.possessions import PossessionTracker
from bball3x3.config import LLMConfig, SimulationConfig, load_llm_config
from bball3x3.engine.loop import play_heuristic_game
from bball3x3.logging.event_log import EventLogger
from bball3x3.referee import (
    LLMReferee,
    LLMRefereeResult,
    Referee,
    RuleRetriever,
    SyncLLMReferee,
)
from bball3x3.referee.index import DEFAULT_INDEX_DIR
from bball3x3.referee.llm_referee import SYSTEM_PROMPT
from bball3x3.schemas.agent import AgentOutput, CoordinationConfig
from bball3x3.schemas.log import (
    DecisionRecord,
    GameEndRecord,
    GameStartRecord,
    GameTotals,
    InvariantViolationRecord,
    PossessionChange,
    PossessionRef,
    RefereeRecord,
    ResolutionRecord,
    ScoringEvent,
    ShotAttempt,
    StateRecord,
    TurnoverEvent,
)

MODEL_SLUG = "heuristic-v1"

if TYPE_CHECKING:
    from bball3x3.llm.base import LLMBackend


def _config_hash(config_snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(
        config_snapshot, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_logged_game(
    *,
    seed: int = 101,
    path: str | Path,
    game_id: str | None = None,
    experiment_id: str = "manual",
    replicate_id: str | None = None,
    config: SimulationConfig | None = None,
    max_events: int = 2000,
    roster_path: str | None = None,
    referee: Referee | LLMReferee | None = None,
    agent_factory: Callable[[str], BasePlayer] | None = None,
    llm_config: LLMConfig | None = None,
    llm_backend: LLMBackend | None = None,
    rule_retriever: RuleRetriever | None = None,
    rule_index_dir: str | Path = DEFAULT_INDEX_DIR,
) -> dict[str, Any]:
    """Play and log a game, selecting the LLM referee when enabled in config.

    An explicitly supplied referee takes priority. ``llm_backend`` and
    ``rule_retriever`` allow API-key-free games with a fake backend in tests.
    """
    game_id = game_id or f"game_{seed}"
    replicate_id = replicate_id or f"seed_{seed}"
    logger = EventLogger(path)
    player_label = "heuristic" if agent_factory is None else "custom-player"
    model_slug = MODEL_SLUG if agent_factory is None else "custom-player"

    tracker: PossessionTracker | None = None
    next_possession = 2  # p0001 belongs to the opening possession
    decisions_by_team = {"A": 0, "B": 0}
    possessions_by_team = {"A": 0, "B": 0}
    events_seen = 0
    final: dict[str, Any] = {"finished": False}

    def _new_possession_id() -> str:
        nonlocal next_possession
        pid = f"p{next_possession:04d}"
        next_possession += 1
        return pid

    def _handle_game_start(payload: dict[str, Any]) -> None:
        nonlocal tracker
        state = payload["state"]
        cfg = payload["config"]
        first = state.offense
        roster = {
            "players": {pid: p.team for pid, p in state.players.items()},
            "captain": "P1",
        }
        snapshot = cfg.model_dump(mode="python")
        prompt_hashes = {"players": model_slug}
        if isinstance(referee_for_game, SyncLLMReferee):
            llm_ref = referee_for_game.referee
            snapshot["llm_referee"] = llm_ref.config.model_dump(mode="python")
            snapshot["rule_index"] = {
                "backend": llm_ref.retriever.backend,
                "model": llm_ref.retriever.model_name,
            }
            prompt_hashes["referee"] = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
        start = GameStartRecord(
            schema_version=1,
            game_id=game_id,
            experiment_id=experiment_id,
            replicate_id=replicate_id,
            seed=payload["seed"],
            first_possession=first,
            team_conditions={"A": player_label, "B": player_label},
            matchup={"home": player_label, "away": player_label},
            coordination={"A": CoordinationConfig(), "B": CoordinationConfig()},
            roster=roster,
            config_hash=_config_hash(snapshot),
            config_snapshot=snapshot,
            prompt_hashes=prompt_hashes,
            model_slug=model_slug,
            code_commit=None,
            initial_state=state.model_copy(deep=True),
            initial_possession_id="p0001",
            initial_memory={"A": [], "B": []},
        )
        logger.write(start)
        tracker = PossessionTracker(start)

    def _handle_event(payload: dict[str, Any]) -> None:
        nonlocal events_seen
        assert tracker is not None
        e = payload["event_idx"]
        events_seen = e
        state = payload["state"]
        event = payload["event"]
        before = tracker.active
        assert before is not None

        for pid, raw in payload["proposals"].items():
            fixed = payload["legalized"][pid]
            rec = payload["remaps"][pid]
            team = pid[:1]
            decisions_by_team[team] += 1
            parsed = AgentOutput(
                action=raw.action.upper(), target=raw.target,
                conduct=raw.conduct, conduct_target=raw.conduct_target,
            )
            if rec is None:
                logger.write(
                    DecisionRecord(
                        event_idx=e,
                        player=pid,
                        team=team,  # type: ignore[arg-type]
                        raw_output=raw.model_dump_json(exclude_none=True),
                        parsed_output=parsed,
                        parse_ok=True,
                        invalid_reason=None,
                        executed_action=fixed.action.upper(),  # type: ignore[arg-type]
                        executed_target=fixed.target,
                    )
                )
            else:
                logger.write(
                    DecisionRecord(
                        event_idx=e,
                        player=pid,
                        team=team,  # type: ignore[arg-type]
                        raw_output=raw.model_dump_json(exclude_none=True),
                        parsed_output=parsed,
                        parse_ok=True,
                        invalid_reason=rec.reason,
                        remapped_action=fixed.action.upper(),  # type: ignore[arg-type]
                        remapped_target=fixed.target,
                        executed_action=fixed.action.upper(),  # type: ignore[arg-type]
                        executed_target=fixed.target,
                    )
                )

        holder = payload["holder"]
        handler = payload["handler_action"]
        trace = payload.get("referee_trace")
        if isinstance(trace, LLMRefereeResult):
            if trace.query != payload["referee_query"]:
                raise ValueError("LLM retrieval query differs from the logged referee query")
            logger.write(trace.as_log_record(
                e,
                decision=payload["referee_decision"],
                rejected_output=payload["referee_rejected_output"],
                rejection_reason=payload["referee_rejection_reason"],
            ))
        else:
            logger.write(RefereeRecord(
                event_idx=e,
                query=payload["referee_query"],
                decision=payload["referee_decision"],
                rejected_output=payload["referee_rejected_output"],
                rejection_reason=payload["referee_rejection_reason"],
            ))

        scoring: list[ScoringEvent] = []
        if event.get("scored") and event.get("points"):
            scoring.append(
                ScoringEvent(
                    team=event["scoring_team"],
                    points=event["points"],
                    source="FIELD_GOAL",
                    possession_id=before.possession_id,
                )
            )
        if event.get("free_throw_points"):
            scoring.append(
                ScoringEvent(
                    team=event["free_throw_team"],
                    points=event["free_throw_points"],
                    source="FREE_THROW",
                    possession_id=before.possession_id,
                )
            )
        changes: list[PossessionChange] = []
        after = before
        if event.get("possession_changed"):
            new_id = _new_possession_id()
            changes.append(
                PossessionChange(
                    from_possession_id=before.possession_id,
                    to_possession_id=new_id,
                    to_team=state.offense,  # type: ignore[arg-type]
                    reason=event.get("possession_reason") or "CONTROL",
                    kind="CONTROL_TRANSFER",
                )
            )
            after = PossessionRef(possession_id=new_id, team=state.offense)  # type: ignore[arg-type]

        shots: list[ShotAttempt] | None = None
        if handler == "SHOOT" and holder is not None:
            shots = [
                ShotAttempt(
                    team=holder[:1],  # type: ignore[arg-type]
                    shooter=holder,
                    made=bool(event.get("points")),
                )
            ]
        turnovers: list[TurnoverEvent] | None = None
        if event.get("turnover"):
            turnovers = [
                TurnoverEvent(
                    team=payload["prev"].offense,  # type: ignore[arg-type]
                    possession_id=before.possession_id,
                    reason=event.get("possession_reason") or "TURNOVER",
                    player=holder,
                )
            ]

        finished = payload["finished"]
        resolution = ResolutionRecord(
            event_idx=e,
            actions={
                pid: p.action.upper()  # type: ignore[misc]
                for pid, p in payload["legalized"].items()
            },
            action_targets={pid: p.target for pid, p in payload["legalized"].items()},
            outcomes=(
                {"conduct_evidence": event["conduct_evidence"]}
                if "conduct_evidence" in event else {}
            ),
            possession_before=before,
            possession_after=None if finished else after,
            scoring_events=scoring,
            possession_changes=changes,
            shots=shots,
            turnovers=turnovers,
            game_over=finished,
            game_end_reason=payload["end_reason"] if finished else None,
        )
        ends = tracker.apply(resolution)
        logger.write(resolution)
        for v in payload["new_violations"]:
            logger.write(
                InvariantViolationRecord(
                    event_idx=e,
                    constraint_id=v["constraint_id"],
                    constraint_name=v["constraint_name"],
                    details=str(v["details"]),
                )
            )
        logger.write(
            StateRecord(
                event_idx=e,
                state=state.model_copy(deep=True),
                invariant_checks_completed=True,
                constraints_checked=list(range(1, 21)),
            )
        )
        for end in ends:
            possessions_by_team[end.team] += 1
            logger.write(end)
        if finished:
            final.update(
                {
                    "finished": True,
                    "end_reason": payload["end_reason"],
                    "score": dict(state.score),
                }
            )

    def _sink(payload: dict[str, Any]) -> None:
        if payload["type"] == "game_start":
            _handle_game_start(payload)
        else:
            _handle_event(payload)

    adapter: SyncLLMReferee | None = None
    try:
        if isinstance(referee, LLMReferee):
            adapter = SyncLLMReferee(referee)
            referee_for_game: Referee = adapter
        elif referee is not None:
            referee_for_game = referee
        elif llm_config is not None and llm_config.referee.enabled and (
            llm_config.referee.backend == "llm"
        ):
            from bball3x3.llm.client import OpenRouterClient

            retriever = rule_retriever or RuleRetriever(
                rule_index_dir, expected_model=llm_config.embeddings.model,
            )
            backend = llm_backend or OpenRouterClient(llm_config)
            adapter = SyncLLMReferee(
                LLMReferee(backend, retriever, llm_config.referee),
                close_backend=llm_backend is None,
            )
            referee_for_game = adapter
        else:
            referee_for_game = referee
        summary = play_heuristic_game(
            seed=seed,
            config=config,
            max_events=max_events,
            roster_path=roster_path,
            on_event=_sink,
            referee=referee_for_game,
            agent_factory=agent_factory,
        )
        game_complete = final["finished"]
        if game_complete:
            logger.write(
                GameEndRecord(
                    last_event_idx=events_seen,
                    end_reason=final["end_reason"],
                    final_score=final["score"],
                    ot_flag=bool(summary.get("overtime_reached")),
                    totals=GameTotals(
                        decisions=sum(decisions_by_team.values()),
                        decisions_by_team=dict(decisions_by_team),  # type: ignore[arg-type]
                        transitions=events_seen,
                        possessions_by_team=dict(possessions_by_team),  # type: ignore[arg-type]
                    ),
                )
            )
    finally:
        logger.close()
        if adapter is not None:
            adapter.close()

    return {
        "path": str(path),
        "events": summary["events"],
        "score": summary["score"],
        "game_complete": game_complete,
        "end_reason": final.get("end_reason"),
        "decisions_by_team": decisions_by_team,
        "possessions_by_team": possessions_by_team,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a logged heuristic game.")
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--path", type=str, default=None)
    parser.add_argument("--game-id", type=str, default=None)
    parser.add_argument("--experiment-id", type=str, default="manual")
    parser.add_argument("--replicate-id", type=str, default=None)
    parser.add_argument("--max-events", type=int, default=2000)
    parser.add_argument("--llm-config", type=str, default=None)
    parser.add_argument("--rule-index-dir", type=str, default=str(DEFAULT_INDEX_DIR))
    args = parser.parse_args()
    path = args.path or f"runs/game_{args.seed}.jsonl"
    result = run_logged_game(
        seed=args.seed,
        path=path,
        game_id=args.game_id,
        experiment_id=args.experiment_id,
        replicate_id=args.replicate_id,
        max_events=args.max_events,
        llm_config=load_llm_config(args.llm_config) if args.llm_config else None,
        rule_index_dir=args.rule_index_dir,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
