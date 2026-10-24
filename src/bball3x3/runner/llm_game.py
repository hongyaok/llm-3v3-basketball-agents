"""Async LLM game runner with WS6 event logging and checkpoint/resume (WS3 §3.6 & §3.9)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from bball3x3.agents.adapter import (
    build_decision_record,
    decision_to_proposal,
)
from bball3x3.agents.context import (
    CoordinationView,
    SimpleCoordinationView,
    build_initial_memory_entries,
)
from bball3x3.agents.filtering import SuppressedItems
from bball3x3.agents.llm_player import DecisionResult, LLMPlayer
from bball3x3.agents.observation import build_observation
from bball3x3.agents.prompting import PromptBuilder
from bball3x3.analysis.possessions import PossessionTracker
from bball3x3.config import (
    InitialMemoryConfig,
    LLMConfig,
    RosterConfig,
    SimulationConfig,
    load_initial_memory_config,
    load_llm_config,
    load_roster_config,
    load_simulation_config,
)
from bball3x3.engine.abilities import build_abilities_map
from bball3x3.engine.session import EngineSession
from bball3x3.llm.base import LLMBackend, LLMResponse
from bball3x3.logging.event_log import EventLogger
from bball3x3.memory.personal import PersonalMemory
from bball3x3.memory.similarity import Embedder
from bball3x3.referee import LLMReferee, LLMRefereeResult, Referee, RuleRetriever, SyncLLMReferee
from bball3x3.referee.index import DEFAULT_INDEX_DIR
from bball3x3.schemas.actions import ActionProposal
from bball3x3.schemas.agent import AgentOutput, CoordinationConfig
from bball3x3.schemas.log import (
    CaptainCallRecord,
    CSProposalRecord,
    CSWriteRecord,
    GameEndRecord,
    GameStartRecord,
    GameTotals,
    InitialMemoryEntry,
    InvariantViolationRecord,
    MemoryProposalRecord,
    MemoryWriteRecord,
    MessageRecord,
    PossessionChange,
    PossessionRef,
    RefereeRecord,
    ResolutionRecord,
    ScoringEvent,
    ShotAttempt,
    StateRecord,
    TurnoverEvent,
)
from bball3x3.schemas.referee import RefereeDecision
from bball3x3.schemas.state import GameState


def _config_hash(
    sim_cfg: SimulationConfig,
    llm_cfg: LLMConfig,
    coordination: dict[str, CoordinationConfig],
    memory_settings: dict[str, Any],
) -> str:
    snapshot = {
        "simulation": sim_cfg.model_dump(mode="python"),
        "llm_players": llm_cfg.players.model_dump(mode="python"),
        "llm_referee": llm_cfg.referee.model_dump(mode="python"),
        "coordination": {k: v.model_dump(mode="python") for k, v in coordination.items()},
        "memory_settings": memory_settings,
    }
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compute_involved_opponents(
    prev: GameState, legalized: dict[str, ActionProposal]
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for pid in prev.players:
        own_team = pid[:1]
        involved: set[str] = set()
        target = legalized[pid].target if pid in legalized else None
        if isinstance(target, str) and target in prev.players and target[:1] != own_team:
            involved.add(target)
        assigned = prev.matchups.get(pid)
        if assigned and assigned in prev.players and assigned[:1] != own_team:
            involved.add(assigned)
        for defender, guarded in prev.matchups.items():
            if guarded == pid and defender in prev.players and defender[:1] != own_team:
                involved.add(defender)
        out[pid] = sorted(involved)
    return out


def _serialize_decision_result(res: DecisionResult) -> dict[str, Any]:
    return {
        "output": res.output.model_dump(mode="json"),
        "kept": res.kept.model_dump(mode="json"),
        "suppressed": {
            "messages": [m.model_dump(mode="json") for m in res.suppressed],
            "captain_call": (
                res.suppressed.captain_call.model_dump(mode="json")
                if res.suppressed.captain_call
                else None
            ),
            "memory_update": (
                res.suppressed.memory_update.model_dump(mode="json")
                if res.suppressed.memory_update
                else None
            ),
            "cs_update": (
                res.suppressed.cs_update.model_dump(mode="json")
                if res.suppressed.cs_update
                else None
            ),
        },
        "observation_text": res.observation_text,
        "raw_attempts": res.raw_attempts,
        "responses": [r.model_dump(mode="json") for r in res.responses],
        "prompt_hash": res.prompt_hash,
    }


def _deserialize_decision_result(data: dict[str, Any]) -> DecisionResult:
    from bball3x3.schemas.memory import CSProposal, MemoryProposal
    from bball3x3.schemas.messages import CaptainCall, Message

    sup_data = data.get("suppressed") or {}
    sup = SuppressedItems(
        [Message.model_validate(m) for m in sup_data.get("messages", [])],
        captain_call=(
            CaptainCall.model_validate(sup_data["captain_call"])
            if sup_data.get("captain_call")
            else None
        ),
        memory_update=(
            MemoryProposal.model_validate(sup_data["memory_update"])
            if sup_data.get("memory_update")
            else None
        ),
        cs_update=(
            CSProposal.model_validate(sup_data["cs_update"])
            if sup_data.get("cs_update")
            else None
        ),
    )
    return DecisionResult(
        output=AgentOutput.model_validate(data["output"]),
        kept=AgentOutput.model_validate(data["kept"]),
        suppressed=sup,
        observation_text=data["observation_text"],
        raw_attempts=list(data.get("raw_attempts", [])),
        responses=[LLMResponse.model_validate(r) for r in data.get("responses", [])],
        prompt_hash=data.get("prompt_hash", ""),
    )


async def run_llm_game(
    *,
    llm: LLMBackend,
    path: str | Path,
    seed: int = 101,
    game_id: str | None = None,
    experiment_id: str = "ws3_llm",
    replicate_id: str | None = None,
    sim_config: SimulationConfig | None = None,
    llm_config: LLMConfig | None = None,
    roster_config: RosterConfig | None = None,
    initial_memory_config: InitialMemoryConfig | None = None,
    coordination: dict[str, CoordinationConfig] | None = None,
    team_conditions: dict[str, str] | None = None,
    coordination_view: CoordinationView | None = None,
    embedder: Embedder | None = None,
    similarity_threshold: float = 0.80,
    max_events: int = 2000,
    checkpoint_path: str | Path | None = None,
    resume: bool = False,
    referee: Referee | LLMReferee | None = None,
    rule_retriever: RuleRetriever | None = None,
    rule_index_dir: str | Path | None = None,
    llm_backend_for_referee: LLMBackend | None = None,
    first_possession: str | None = None,
) -> dict[str, Any]:
    """Run an async 6-player LLM game with full WS6 JSONL logging and checkpoint support."""
    log_path = Path(path)
    ckpt_path = Path(checkpoint_path) if checkpoint_path else log_path.with_suffix(".ckpt.json")

    sim_cfg = sim_config or load_simulation_config()
    llm_cfg = llm_config or load_llm_config()
    roster_cfg = roster_config or load_roster_config()
    init_mem_cfg = (
        initial_memory_config
        if initial_memory_config is not None
        else load_initial_memory_config()
    )
    coord_flags: dict[str, CoordinationConfig] = coordination or {
        "A": CoordinationConfig(),
        "B": CoordinationConfig(),
    }
    cond_labels = team_conditions or {"A": "A_full", "B": "A_full"}

    if embedder is None:
        memory_settings = {
            "backend": "exact",
            "model": None,
            "similarity_threshold": None,
        }
    else:
        memory_settings = {
            "backend": "embedding",
            "model": getattr(
                embedder,
                "model_name",
                getattr(embedder, "__qualname__", type(embedder).__qualname__),
            ),
            "similarity_threshold": similarity_threshold,
        }

    config_identity = _config_hash(
        sim_cfg, llm_cfg, coord_flags, memory_settings
    )
    game_id = game_id or f"llm_game_{seed}"
    replicate_id = replicate_id or f"seed_{seed}"

    saved_event_decisions: list[dict[str, dict[str, Any]]] = []
    if resume and ckpt_path.exists():
        ckpt_payload = json.loads(ckpt_path.read_text(encoding="utf-8"))
        if ckpt_payload.get("config_hash") != config_identity:
            raise ValueError(
                "Checkpoint configuration differs from this run, "
                "or the checkpoint predates config identity validation"
            )
        if ckpt_payload.get("seed") != seed:
            raise ValueError("Checkpoint seed differs from this run")
        if ckpt_payload.get("first_possession") != first_possession:
            raise ValueError("Checkpoint first possession differs from this run")
        saved_event_decisions = list(ckpt_payload.get("events", []))
        if log_path.exists():
            log_path.unlink()
    elif resume and log_path.exists():
        log_path.unlink()

    abilities_map = build_abilities_map(roster_cfg)
    adapter: SyncLLMReferee | None = None
    referee_for_game: Referee | SyncLLMReferee | None = None
    if isinstance(referee, LLMReferee):
        adapter = SyncLLMReferee(referee)
        referee_for_game = adapter
    elif referee is not None:
        referee_for_game = referee
    elif llm_cfg.referee.enabled and llm_cfg.referee.backend == "llm":
        from bball3x3.llm.client import OpenRouterClient

        retriever = rule_retriever or RuleRetriever(
            rule_index_dir or DEFAULT_INDEX_DIR,
            expected_model=llm_cfg.embeddings.model,
        )
        ref_backend = llm_backend_for_referee or OpenRouterClient(llm_cfg)
        adapter = SyncLLMReferee(
            LLMReferee(ref_backend, retriever, llm_cfg.referee),
            close_backend=llm_backend_for_referee is None,
        )
        referee_for_game = adapter
    session = EngineSession(
        seed=seed,
        config=sim_cfg,
        abilities_map=abilities_map,
        referee=referee_for_game,
        first_possession=first_possession,
    )

    init_mem_entries = build_initial_memory_entries(init_mem_cfg)
    coord_view = (
        coordination_view
        if coordination_view is not None
        else SimpleCoordinationView(
            initial_memory=init_mem_entries,
            captains={
                team: f"{team}{roster_cfg.captain[1:]}"
                for team in ("A", "B")
            },
            active_players=set(session.state.players),
            embedder=embedder,
            similarity_threshold=similarity_threshold,
        )
    )
    personal_memories = {pid: PersonalMemory(pid) for pid in session.state.players}
    prompt_builder = PromptBuilder(roster=roster_cfg, court_config=sim_cfg.court)

    captain_slot_num = roster_cfg.captain[1:] if len(roster_cfg.captain) > 1 else "1"
    captains = {"A": f"A{captain_slot_num}", "B": f"B{captain_slot_num}"}

    profiles_by_slot = {p.slot.upper(): p for p in roster_cfg.players}
    agents: dict[str, LLMPlayer] = {}
    for pid in sorted(session.state.players):
        team = pid[:1]
        slot = f"P{pid[1:]}"
        agents[pid] = LLMPlayer(
            pid,
            llm,
            llm_cfg.players,
            prompt_builder=prompt_builder,
            profile=profiles_by_slot.get(slot),
            flags=coord_flags[team],
            is_captain=(pid == captains[team]),
        )

    prompt_hashes: dict[str, str] = {}
    for team in ("A", "B"):
        for is_cap in (True, False):
            role_key = f"team_{team}_{'captain' if is_cap else 'player'}"
            prompt_hashes[role_key] = prompt_builder.template_hash(
                coord_flags[team],
                is_captain=is_cap,
                output_format=llm_cfg.players.output_format,
                include_rationale=llm_cfg.players.include_rationale,
            )

    initial_memory_log = {
        team: [
            InitialMemoryEntry(
                id=e.id,
                opponent=e.opponent,
                category=e.category,  # type: ignore[arg-type]
                tendency=e.tendency,
            )
            for e in entries
        ]
        for team, entries in init_mem_entries.items()
    }

    start_record = GameStartRecord(
        schema_version=1,
        game_id=game_id,
        experiment_id=experiment_id,
        replicate_id=replicate_id,
        seed=seed,
        first_possession=session.state.offense,
        team_conditions=cond_labels,  # type: ignore[arg-type]
        matchup={"home": cond_labels["A"], "away": cond_labels["B"]},
        coordination=coord_flags,  # type: ignore[arg-type]
        roster={
            "players": {pid: p.team for pid, p in session.state.players.items()},
            "captain": roster_cfg.captain,
        },
        config_hash=config_identity,
        config_snapshot={
            "simulation": sim_cfg.model_dump(mode="python"),
            "llm_players": llm_cfg.players.model_dump(mode="python"),
            "llm_referee": llm_cfg.referee.model_dump(mode="python"),
            "referee_effective": {
                "has_referee": referee_for_game is not None,
                "adapter": type(adapter).__name__ if adapter is not None else None,
                "explicit_referee": type(referee).__name__ if referee is not None else None,
                "override_note": (
                    "referee.enabled/backend in-memory only; configs untouched"
                ),
            },
            "coordination": {k: v.model_dump(mode="python") for k, v in coord_flags.items()},
            "memory_settings": memory_settings,
        },
        prompt_hashes=prompt_hashes,
        model_slug=llm_cfg.players.model,
        code_commit=None,
        initial_state=session.state.model_copy(deep=True),
        initial_possession_id="p0001",
        initial_memory=initial_memory_log,  # type: ignore[arg-type]
    )

    logger = EventLogger(log_path)
    tracker = PossessionTracker(start_record)
    next_possession = 2
    decisions_by_team = {"A": 0, "B": 0}
    possessions_by_team = {"A": 0, "B": 0}
    total_cost_usd = 0.0
    parse_failures = 0
    invalid_decisions = 0
    total_decisions = 0

    def _new_possession_id() -> str:
        nonlocal next_possession
        pid = f"p{next_possession:04d}"
        next_possession += 1
        return pid

    def _save_checkpoint() -> None:
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        ckpt_path.write_text(
            json.dumps(
            {
                "game_id": game_id,
                "seed": seed,
                "first_possession": first_possession,
                "config_hash": config_identity,
                "events": saved_event_decisions,
            }
            ),
            encoding="utf-8",
        )

    try:
        logger.write(start_record)
        player_ids = sorted(session.state.players)

        while session.events < max_events:
            upcoming_event_idx = session.events + 1

            if upcoming_event_idx <= len(saved_event_decisions):
                # Replay from checkpoint without calling LLM
                raw_saved = saved_event_decisions[upcoming_event_idx - 1]
                decision_results = {
                    pid: _deserialize_decision_result(raw_saved[pid]) for pid in player_ids
                }
            else:
                observations = {
                    pid: build_observation(
                        session.state,
                        pid,
                        coordination=coord_view,
                        personal_memory=personal_memories[pid],
                        flags=coord_flags[pid[:1]],
                        is_captain=(pid == captains[pid[:1]]),
                        decision_event_idx=upcoming_event_idx,
                    )
                    for pid in player_ids
                }
                gathered = await asyncio.gather(
                    *(agents[pid].decide(observations[pid]) for pid in player_ids)
                )
                decision_results = dict(zip(player_ids, gathered))
                saved_event_decisions.append(
                    {
                        pid: _serialize_decision_result(decision_results[pid])
                        for pid in player_ids
                    }
                )
                _save_checkpoint()

            proposals = {
                pid: decision_to_proposal(pid, decision_results[pid]) for pid in player_ids
            }
            payload = session.step(proposals)
            e = payload["event_idx"]
            state = payload["state"]
            event = payload["event"]
            before = tracker.active
            assert before is not None

            # 1. Write 6 DecisionRecords
            for pid in player_ids:
                res = decision_results[pid]
                fixed = payload["legalized"][pid]
                remap = payload["remaps"][pid]
                if not res.kept.parse_ok and remap is not None and remap.reason != "PARSE_FAIL":
                    remap = remap.model_copy(update={"reason": "PARSE_FAIL"})

                rec = build_decision_record(
                    event_idx=e,
                    player_id=pid,
                    result=res,
                    fixed=fixed,
                    remap=remap,
                )
                logger.write(rec)
                team = pid[:1]
                decisions_by_team[team] += 1
                total_decisions += 1
                total_cost_usd += res.cost_usd
                if not rec.parse_ok:
                    parse_failures += 1
                if rec.invalid_reason is not None:
                    invalid_decisions += 1

            # 2. Write MessageRecords and CaptainCallRecords (kept + suppressed)
            for pid in player_ids:
                res = decision_results[pid]
                team = pid[:1]
                if not res.kept.parse_ok:
                    continue

                for msg in res.kept.messages:
                    logger.write(
                        MessageRecord(
                            event_idx=e,
                            sender=pid,
                            team=team,  # type: ignore[arg-type]
                            channel="captain" if msg.is_captain_channel else "teammate",
                            kind=msg.kind,
                            text=msg.text,
                            directive=msg.directive,
                            cs=msg.cs,
                            delivered_at=e + 1,
                            suppressed=False,
                        )
                    )

                if res.kept.captain_call is not None:
                    call = res.kept.captain_call
                    logger.write(
                        CaptainCallRecord(
                            event_idx=e,
                            team=team,  # type: ignore[arg-type]
                            maintain=call.maintain,
                            tactic=call.tactic.text if call.tactic else None,
                            cs=call.tactic.cs if call.tactic else None,
                            directives=[
                                d.model_dump(mode="python") for d in call.directives
                            ],
                        )
                    )
                    if call.tactic is not None:
                        logger.write(
                            MessageRecord(
                                event_idx=e,
                                sender=pid,
                                team=team,  # type: ignore[arg-type]
                                channel="captain",
                                kind="tactic",
                                text=call.tactic.text,
                                directive=None,
                                cs=call.tactic.cs,
                                delivered_at=e + 1,
                                suppressed=False,
                            )
                        )
                    for d_msg in call.directives:
                        logger.write(
                            MessageRecord(
                                event_idx=e,
                                sender=pid,
                                team=team,  # type: ignore[arg-type]
                                channel="captain",
                                kind="action",
                                text=d_msg.text,
                                directive=d_msg.directive,
                                cs=d_msg.cs,
                                delivered_at=e + 1,
                                suppressed=False,
                            )
                        )

                for sup_msg in res.suppressed:
                    logger.write(
                        MessageRecord(
                            event_idx=e,
                            sender=pid,
                            team=team,  # type: ignore[arg-type]
                            channel="captain" if sup_msg.is_captain_channel else "teammate",
                            kind=sup_msg.kind,
                            text=sup_msg.text,
                            directive=sup_msg.directive,
                            cs=sup_msg.cs,
                            delivered_at=None,
                            suppressed=True,
                        )
                    )

                # Suppressed memory / CS proposals when memory_write is False
                if res.suppressed.memory_update is not None:
                    logger.write(
                        MemoryProposalRecord(
                            event_idx=e,
                            team=team,  # type: ignore[arg-type]
                            player=pid,
                            proposal=res.suppressed.memory_update,
                            accepted=False,
                        )
                    )
                if res.suppressed.cs_update is not None:
                    logger.write(
                        CSProposalRecord(
                            event_idx=e,
                            team=team,  # type: ignore[arg-type]
                            player=pid,
                            proposal=res.suppressed.cs_update,
                            accepted=False,
                        )
                    )

            # Update coordination view for t+1 and write memory/CS records
            kept_map = {
                pid: decision_results[pid].kept
                for pid in player_ids
                if decision_results[pid].kept.parse_ok
            }
            if isinstance(coord_view, SimpleCoordinationView):
                mem_writes, cs_writes = coord_view.record_event(e, kept_map, coord_flags)
                for mw in mem_writes:
                    logger.write(
                        MemoryProposalRecord(
                            event_idx=e,
                            team=mw["team"],
                            player=mw["player"],
                            proposal=mw["proposal"],
                            accepted=mw["accepted"],
                            merged_into=mw["merged_into"],
                            new_id=mw["new_id"],
                            confidence_after=mw["confidence_after"],
                        )
                    )

                    if not mw["accepted"]:
                        continue

                    entry = mw["entry"]
                    logger.write(
                        MemoryWriteRecord(
                            event_idx=e,
                            team=mw["team"],
                            memory_id=entry.id,
                            opponent=entry.opponent,
                            category=entry.category,
                            tendency=entry.tendency,
                            visible_at=mw["visible_at"],
                            evicted_ids=mw["evicted_ids"],
                        )
                    )
                for cw in cs_writes:
                    logger.write(
                        CSProposalRecord(
                            event_idx=e,
                            team=cw["team"],
                            player=cw["player"],
                            proposal=cw["proposal"],
                            accepted=cw["accepted"],
                            key=cw["key"],
                            merged=cw["merged"],
                        )
                    )

                    if not cw["accepted"]:
                        continue

                    entry = cw["entry"]
                    logger.write(
                        CSWriteRecord(
                            event_idx=e,
                            team=cw["team"],
                            key=entry.key,
                            side=entry.side,
                            opponent_strategy=entry.opponent_strategy,
                            counter_strategy=entry.counter_strategy,
                            merged=cw["merged"],
                            visible_at=cw["visible_at"],
                        )
                    )

            # Update PersonalMemory for each player
            for pid in player_ids:
                personal_memories[pid].update(payload["prev"], session.state, payload)

            # 3. RefereeRecord
            holder = payload["holder"]
            handler = payload["handler_action"]
            trace = payload.get("referee_trace")
            if isinstance(trace, LLMRefereeResult):
                logger.write(
                    trace.as_log_record(
                        e,
                        decision=payload["referee_decision"],
                        rejected_output=payload.get("referee_rejected_output"),
                        rejection_reason=payload.get("referee_rejection_reason"),
                    )
                )
            else:
                logger.write(
                    RefereeRecord(
                        event_idx=e,
                        query=payload.get("referee_query") or f"event {e}",
                        decision=payload.get("referee_decision") or RefereeDecision(),
                        rejected_output=payload.get("referee_rejected_output"),
                        rejection_reason=payload.get("referee_rejection_reason"),
                    )
                )

            # 4. ResolutionRecord
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
                        made=bool(event.get("scored")),
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
                involved_opponents=_compute_involved_opponents(
                    payload["prev"], payload["legalized"]
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

            # 5. InvariantViolationRecords
            for v in payload["new_violations"]:
                logger.write(
                    InvariantViolationRecord(
                        event_idx=e,
                        constraint_id=v["constraint_id"],
                        constraint_name=v["constraint_name"],
                        details=str(v["details"]),
                    )
                )

            # 6. StateRecord
            logger.write(
                StateRecord(
                    event_idx=e,
                    state=state.model_copy(deep=True),
                    invariant_checks_completed=True,
                    constraints_checked=list(range(1, 21)),
                )
            )

            # 7. PossessionEndRecords
            for end in ends:
                possessions_by_team[end.team] += 1
                logger.write(end)

            if session.finished:
                break

        game_complete = session.finished
        if game_complete:
            logger.write(
                GameEndRecord(
                    last_event_idx=session.events,
                    end_reason=session.end_reason or "CLOCK_EXPIRED",  # type: ignore[arg-type]
                    final_score=dict(session.state.score),  # type: ignore[arg-type]
                    ot_flag=session.ot_baseline is not None,
                    totals=GameTotals(
                        decisions=sum(decisions_by_team.values()),
                        decisions_by_team=dict(decisions_by_team),  # type: ignore[arg-type]
                        transitions=session.events,
                        possessions_by_team=dict(possessions_by_team),  # type: ignore[arg-type]
                    ),
                    total_cost_usd=total_cost_usd,
                )
            )
            if ckpt_path.exists():
                ckpt_path.unlink()
    finally:
        logger.close()
        if adapter is not None:
            adapter.close()

    return {
        "path": str(log_path),
        "events": session.events,
        "score": dict(session.state.score),
        "game_complete": session.finished,
        "end_reason": session.end_reason,
        "decisions_by_team": decisions_by_team,
        "possessions_by_team": possessions_by_team,
        "parse_failure_rate": parse_failures / max(total_decisions, 1),
        "iar": invalid_decisions / max(total_decisions, 1),
        "total_cost_usd": total_cost_usd,
    }
