"""Prompt harness for evaluating LLMPlayer across 20 fixed basketball scenarios (WS3 §5).

Usage:
  uv run python scripts/prompt_harness.py --fake --samples 1
  uv run python scripts/prompt_harness.py --samples 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure src/ is importable when running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bball3x3.agents.adapter import legalize_decision
from bball3x3.agents.context import StaticCoordinationView
from bball3x3.agents.llm_player import LLMPlayer
from bball3x3.agents.observation import build_observation
from bball3x3.agents.prompting import PromptBuilder
from bball3x3.config import (
    SimulationConfig,
    load_initial_memory_config,
    load_llm_config,
    load_roster_config,
    load_simulation_config,
)
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.state import create_initial_state
from bball3x3.llm import FakeLLM, LegalXMLPolicy, OpenRouterClient
from bball3x3.memory.personal import PersonalMemory
from bball3x3.schemas.agent import CoordinationConfig
from bball3x3.schemas.memory import CSEntry, MemoryEntry
from bball3x3.schemas.messages import CaptainCall, Directive, Message
from bball3x3.schemas.state import BallState, GameState


@dataclass
class HarnessScenario:
    id: str
    description: str
    player_id: str
    is_captain: bool
    flags: CoordinationConfig
    state: GameState
    coordination: StaticCoordinationView = field(default_factory=StaticCoordinationView)
    personal_notes: list[tuple[int, str]] = field(default_factory=list)
    expected_directive: Directive | None = None


def build_scenarios(sim_cfg: SimulationConfig) -> list[HarnessScenario]:
    """Construct 20 fixed scenarios spanning roles, team conditions, and edge cases."""
    base = create_initial_state(sim_cfg, GameRNG.from_seed(101), first_possession="A")

    def clone_state(**updates: Any) -> GameState:
        st = base.model_copy(deep=True)
        for k, v in updates.items():
            setattr(st, k, v)
        return st

    mem_entries = [
        MemoryEntry(
            id="M01",
            opponent="B1",
            category="defensive_tendency",
            tendency="Over-helps in paint and leaves perimeter open.",
        ),
        MemoryEntry(
            id="M02",
            opponent="B2",
            category="offensive_tendency",
            tendency="Drives right aggressively when isolated on wing.",
        ),
    ]
    cs_entries = [
        CSEntry(
            key="01",
            side="offense",
            opponent_strategy="Paint pack help defense",
            counter_strategy="Kick out to open wing shooter",
            created_by="A1",
        ),
        CSEntry(
            key="02",
            side="defense",
            opponent_strategy="High ball screen",
            counter_strategy="Switch screen and contest pull-up",
            created_by="B1",
        ),
    ]

    full_coord = StaticCoordinationView(
        shared_memories={"A": mem_entries, "B": mem_entries},
        cs_tables={"A": cs_entries, "B": cs_entries},
    )

    scenarios: list[HarnessScenario] = []

    def _sync_holder(
        st: GameState, holder: str | None, pos: tuple[int, int], status: str = "HELD"
    ) -> None:
        st.ball = BallState(status=status, pos=pos, holder=holder)  # type: ignore[arg-type]
        for pid, p in st.players.items():
            p.has_ball = pid == holder

    # 1. Open shot for ball handler (A1 captain, Team A full)
    st1 = clone_state()
    st1.players["A1"].pos = (7, 5)
    st1.players["B1"].pos = (3, 2)
    _sync_holder(st1, "A1", (7, 5))
    scenarios.append(
        HarnessScenario(
            id="01_open_shot_ball_handler",
            description="Ball handler A1 wide open at top of arc",
            player_id="A1",
            is_captain=True,
            flags=CoordinationConfig(),
            state=st1,
            coordination=full_coord,
        )
    )

    # 2. Needs-clear after defensive rebound (A1 ball inside arc, needs_clear=True)
    st2 = clone_state(needs_clear=True)
    st2.players["A1"].pos = (7, 2)
    _sync_holder(st2, "A1", (7, 2))
    scenarios.append(
        HarnessScenario(
            id="02_needs_clear_ball_handler",
            description="Ball handler A1 inside arc with needs_clear=True",
            player_id="A1",
            is_captain=True,
            flags=CoordinationConfig(),
            state=st2,
            coordination=full_coord,
        )
    )

    # 3. Shot clock low (<= 2s) forcing quick shot
    st3 = clone_state(shot_clock_s=2)
    st3.players["A2"].pos = (11, 4)
    _sync_holder(st3, "A2", (11, 4))
    scenarios.append(
        HarnessScenario(
            id="03_shot_clock_low",
            description="Ball handler A2 with 2s on shot clock",
            player_id="A2",
            is_captain=False,
            flags=CoordinationConfig(),
            state=st3,
            coordination=full_coord,
        )
    )

    # 4. Off-ball cut opportunity (A2 on wing, paint open)
    st4 = clone_state()
    st4.players["A2"].pos = (2, 5)
    st4.players["B2"].pos = (2, 7)
    scenarios.append(
        HarnessScenario(
            id="04_off_ball_cut_opportunity",
            description="Off-ball A2 with open lane to basket",
            player_id="A2",
            is_captain=False,
            flags=CoordinationConfig(),
            state=st4,
            coordination=full_coord,
        )
    )

    # 5. Off-ball player receiving a captain SCREEN directive
    dir5 = Directive(to="A3", act="SCREEN", target="B1")
    msg5 = Message(
        sender="A1",
        is_captain_channel=True,
        kind="action",
        text="A3 set a screen on B1 now",
        directive=dir5,
    )
    coord5 = StaticCoordinationView(
        captain_calls={"A": CaptainCall(directives=[msg5])},
        team_messages={"A": [msg5]},
        shared_memories={"A": mem_entries},
        cs_tables={"A": cs_entries},
    )
    scenarios.append(
        HarnessScenario(
            id="05_off_ball_captain_screen_directive",
            description="Off-ball A3 receives captain directive to SCREEN B1",
            player_id="A3",
            is_captain=False,
            flags=CoordinationConfig(),
            state=clone_state(),
            coordination=coord5,
            expected_directive=dir5,
        )
    )

    # 6. Ball handler receiving teammate PASS directive
    dir6 = Directive(to="A1", act="PASS", target="A2")
    msg6 = Message(
        sender="A2",
        is_captain_channel=False,
        kind="action",
        text="I am wide open on left wing, pass to A2!",
        directive=dir6,
    )
    coord6 = StaticCoordinationView(
        team_messages={"A": [msg6]},
        shared_memories={"A": mem_entries},
        cs_tables={"A": cs_entries},
    )
    scenarios.append(
        HarnessScenario(
            id="06_ball_handler_pass_directive",
            description="Ball handler A1 receives teammate directive to PASS to A2",
            player_id="A1",
            is_captain=True,
            flags=CoordinationConfig(),
            state=clone_state(),
            coordination=coord6,
            expected_directive=dir6,
        )
    )

    # 7. On-ball defender facing a drive (B1 defending A1)
    st7 = clone_state()
    st7.players["A1"].pos = (7, 4)
    st7.players["B1"].pos = (7, 3)
    _sync_holder(st7, "A1", (7, 4))
    scenarios.append(
        HarnessScenario(
            id="07_on_ball_defender_drive",
            description="Defender B1 guarding ball handler A1 at nail",
            player_id="B1",
            is_captain=True,
            flags=CoordinationConfig(),
            state=st7,
            coordination=full_coord,
        )
    )

    # 8. Help defense scenario (B3 off-ball defender near paint)
    st8 = clone_state()
    st8.players["A1"].pos = (6, 2)
    st8.players["B3"].pos = (9, 2)
    _sync_holder(st8, "A1", (6, 2))
    scenarios.append(
        HarnessScenario(
            id="08_off_ball_defender_help_paint",
            description="Off-ball defender B3 rotating to help paint",
            player_id="B3",
            is_captain=False,
            flags=CoordinationConfig(),
            state=st8,
            coordination=full_coord,
        )
    )

    # 9. Rebound phase — offensive player A3
    st9 = clone_state()
    _sync_holder(st9, None, (7, 1), status="LOOSE")
    scenarios.append(
        HarnessScenario(
            id="09_rebound_offense",
            description="Offensive player A3 during loose-ball rebound",
            player_id="A3",
            is_captain=False,
            flags=CoordinationConfig(),
            state=st9,
            coordination=full_coord,
        )
    )

    # 10. Rebound phase — defensive player B3
    st10 = clone_state()
    _sync_holder(st10, None, (7, 1), status="LOOSE")
    scenarios.append(
        HarnessScenario(
            id="10_rebound_defense",
            description="Defensive player B3 during loose-ball rebound",
            player_id="B3",
            is_captain=False,
            flags=CoordinationConfig(),
            state=st10,
            coordination=full_coord,
        )
    )

    # 11. Captain with no prior call on offense
    scenarios.append(
        HarnessScenario(
            id="11_captain_no_prior_call",
            description="Captain A1 initiating half-court set with no prior call",
            player_id="A1",
            is_captain=True,
            flags=CoordinationConfig(),
            state=clone_state(),
            coordination=StaticCoordinationView(
                shared_memories={"A": mem_entries}, cs_tables={"A": cs_entries}
            ),
        )
    )

    # 12. Team B (comms=False) non-captain receiving captain call
    dir12 = Directive(to="A2", act="SPOT_UP", target="LEFT_CORNER")
    msg12 = Message(
        sender="A1",
        is_captain_channel=True,
        kind="action",
        text="Spot up in left corner",
        directive=dir12,
    )
    coord12 = StaticCoordinationView(
        captain_calls={"A": CaptainCall(directives=[msg12])},
        shared_memories={"A": mem_entries},
        cs_tables={"A": cs_entries},
    )
    scenarios.append(
        HarnessScenario(
            id="12_team_b_non_captain_with_call",
            description="Team B (comms=False) non-captain A2 with captain call",
            player_id="A2",
            is_captain=False,
            flags=CoordinationConfig(comms=False, memory=True, cs=True),
            state=clone_state(),
            coordination=coord12,
            expected_directive=dir12,
        )
    )

    # 13. Team B captain (comms=False, can still emit captain call)
    scenarios.append(
        HarnessScenario(
            id="13_team_b_captain",
            description="Team B (comms=False) captain A1 on offense",
            player_id="A1",
            is_captain=True,
            flags=CoordinationConfig(comms=False, memory=True, cs=True),
            state=clone_state(),
            coordination=full_coord,
        )
    )

    # 14. Team C (comms=True, memory=False, cs=False) ball handler
    scenarios.append(
        HarnessScenario(
            id="14_team_c_ball_handler",
            description="Team C (comms only) ball handler A1",
            player_id="A1",
            is_captain=True,
            flags=CoordinationConfig(comms=True, memory=False, cs=False),
            state=clone_state(),
            coordination=full_coord,
        )
    )

    # 15. Team D (comms=False, memory=False, cs=False) isolated player
    scenarios.append(
        HarnessScenario(
            id="15_team_d_isolated_player",
            description="Team D (no coordination) off-ball player A2",
            player_id="A2",
            is_captain=False,
            flags=CoordinationConfig(comms=False, memory=False, cs=False),
            state=clone_state(),
            coordination=full_coord,
        )
    )

    # 16. Exploitable opponent tendency in shared memory (M01)
    st16 = clone_state()
    st16.players["B1"].pos = (7, 2)  # B1 sagging into paint
    scenarios.append(
        HarnessScenario(
            id="16_exploitable_memory_tendency",
            description="A1 sees B1 sagging in paint matching memory M01",
            player_id="A1",
            is_captain=True,
            flags=CoordinationConfig(),
            state=st16,
            coordination=full_coord,
            personal_notes=[(1, "B1 left A2 open on perimeter last trip")],
        )
    )

    # 17. Counter-strategy table reference on defense
    st17 = clone_state()
    st17.players["A3"].pos = (7, 6)
    st17.players["B2"].pos = (8, 6)
    scenarios.append(
        HarnessScenario(
            id="17_defense_cs_switch",
            description="Defender B2 facing high screen matching CS 02",
            player_id="B2",
            is_captain=False,
            flags=CoordinationConfig(),
            state=st17,
            coordination=full_coord,
        )
    )

    # 18. Overtime with score tied 14-14
    st18 = clone_state(phase="OT", game_clock_s=0, score={"A": 14, "B": 14})
    scenarios.append(
        HarnessScenario(
            id="18_overtime_tied",
            description="Overtime tied 14-14, sudden-death / +2 target",
            player_id="A1",
            is_captain=True,
            flags=CoordinationConfig(),
            state=st18,
            coordination=full_coord,
        )
    )

    # 19. Fast break / check-ball transition after turnover
    st19 = clone_state(offense="B")
    st19.players["B1"].pos = (7, 8)
    st19.players["B2"].pos = (2, 4)
    st19.players["A1"].pos = (7, 6)
    _sync_holder(st19, "B1", (7, 8))
    scenarios.append(
        HarnessScenario(
            id="19_team_b_offense_initiation",
            description="Team B ball handler B1 at check spot",
            player_id="B1",
            is_captain=True,
            flags=CoordinationConfig(),
            state=st19,
            coordination=full_coord,
        )
    )

    # 20. Defender receiving captain directive to STEAL
    dir20 = Directive(to="B1", act="STEAL", target="A1")
    msg20 = Message(
        sender="B1",
        is_captain_channel=True,
        kind="action",
        text="Press A1 and go for steal",
        directive=dir20,
    )
    coord20 = StaticCoordinationView(
        captain_calls={"B": CaptainCall(directives=[msg20])},
        team_messages={"B": [msg20]},
        shared_memories={"B": mem_entries},
        cs_tables={"B": cs_entries},
    )
    st20 = clone_state()
    st20.players["A1"].pos = (7, 6)
    st20.players["B1"].pos = (7, 5)
    scenarios.append(
        HarnessScenario(
            id="20_defender_steal_directive",
            description="On-ball defender B1 adjacent to A1 with STEAL directive",
            player_id="B1",
            is_captain=True,
            flags=CoordinationConfig(),
            state=st20,
            coordination=coord20,
            expected_directive=dir20,
        )
    )

    return scenarios


async def run_harness(
    *,
    use_fake: bool = False,
    samples: int = 1,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    sim_cfg = load_simulation_config()
    roster_cfg = load_roster_config()
    llm_cfg = load_llm_config()
    llm_cfg.runtime.cache = {"enabled": False}
    _ = load_initial_memory_config()

    if use_fake:
        backend: Any = FakeLLM(LegalXMLPolicy())
    else:
        backend = OpenRouterClient(llm_cfg)

    prompt_builder = PromptBuilder(roster=roster_cfg, court_config=sim_cfg.court)
    p_hash = prompt_builder.template_hash(
        CoordinationConfig(),
        is_captain=True,
        output_format=llm_cfg.players.output_format,
        include_rationale=llm_cfg.players.include_rationale,
    )

    scenarios = build_scenarios(sim_cfg)
    profiles_by_slot = {p.slot.upper(): p for p in roster_cfg.players}

    total_runs = 0
    first_try_parse_ok = 0
    final_parse_ok = 0
    repaired_count = 0
    iar_reasons: Counter[str] = Counter()
    directives_emitted = 0
    directive_eligible = 0
    directive_followed = 0
    memory_ref_used = 0
    cs_ref_used = 0
    prompt_tokens_list: list[int] = []
    completion_tokens_list: list[int] = []
    latencies_ms: list[float] = []
    total_cost_usd = 0.0
    per_scenario_results: list[dict[str, Any]] = []

    for sc in scenarios:
        slot = f"P{sc.player_id[1:]}"
        pm = PersonalMemory(sc.player_id)
        for ev_idx, note in sc.personal_notes:
            pm.append_line(f"E{ev_idx}: {note}")

        obs = build_observation(
            sc.state,
            sc.player_id,
            coordination=sc.coordination,
            personal_memory=pm,
            flags=sc.flags,
            is_captain=sc.is_captain,
            decision_event_idx=2,
        )
        player = LLMPlayer(
            sc.player_id,
            backend,
            llm_cfg.players,
            prompt_builder=prompt_builder,
            profile=profiles_by_slot.get(slot),
            flags=sc.flags,
            is_captain=sc.is_captain,
        )

        sc_samples: list[dict[str, Any]] = []
        for s_idx in range(samples):
            res = await player.decide(obs)
            fixed, remap = legalize_decision(sc.state, sc.player_id, res)

            total_runs += 1
            if res.kept.parse_ok and not res.repaired:
                first_try_parse_ok += 1
            if res.kept.parse_ok:
                final_parse_ok += 1
            if res.repaired:
                repaired_count += 1
            if remap is not None:
                iar_reasons[remap.reason] += 1

            if res.kept.messages or res.kept.captain_call is not None:
                directives_emitted += 1

            if sc.expected_directive is not None:
                directive_eligible += 1
                if fixed.action == sc.expected_directive.act and (
                    sc.expected_directive.target is None
                    or fixed.target == sc.expected_directive.target
                ):
                    directive_followed += 1

            if res.kept.memory_ref:
                memory_ref_used += 1
            if (
                any(m.cs is not None for m in res.kept.messages)
                or (
                    res.kept.captain_call is not None
                    and res.kept.captain_call.tactic is not None
                    and res.kept.captain_call.tactic.cs is not None
                )
                or res.kept.cs_update is not None
            ):
                cs_ref_used += 1

            prompt_tokens_list.append(res.prompt_tokens)
            completion_tokens_list.append(res.completion_tokens)
            latencies_ms.append(res.latency_ms)
            total_cost_usd += res.cost_usd

            sc_samples.append(
                {
                    "sample": s_idx + 1,
                    "parse_ok": res.kept.parse_ok,
                    "repaired": res.repaired,
                    "proposed_action": res.kept.action,
                    "proposed_target": res.kept.target,
                    "executed_action": fixed.action,
                    "executed_target": fixed.target,
                    "invalid_reason": remap.reason if remap else None,
                    "memory_ref": res.kept.memory_ref,
                    "prompt_tokens": res.prompt_tokens,
                    "completion_tokens": res.completion_tokens,
                    "latency_ms": res.latency_ms,
                    "finish_reason": res.responses[-1].finish_reason if res.responses else None,
                }
            )

        per_scenario_results.append(
            {
                "id": sc.id,
                "description": sc.description,
                "player_id": sc.player_id,
                "is_captain": sc.is_captain,
                "flags": sc.flags.model_dump(mode="python"),
                "samples": sc_samples,
            }
        )

    sorted_lat = sorted(latencies_ms) if latencies_ms else [0.0]
    p50_lat = statistics.median(sorted_lat)
    p95_idx = min(len(sorted_lat) - 1, int(round(0.95 * (len(sorted_lat) - 1))))
    p95_lat = sorted_lat[p95_idx]

    report = {
        "prompt_hash": p_hash,
        "model": "FakeLLM(LegalXMLPolicy)" if use_fake else llm_cfg.players.model,
        "scenarios_count": len(scenarios),
        "samples_per_scenario": samples,
        "total_runs": total_runs,
        "parse_ok_before_repair_rate": first_try_parse_ok / max(total_runs, 1),
        "parse_ok_after_repair_rate": final_parse_ok / max(total_runs, 1),
        "parse_failure_rate": 1.0 - (final_parse_ok / max(total_runs, 1)),
        "repair_rate": repaired_count / max(total_runs, 1),
        "iar_rate": sum(iar_reasons.values()) / max(total_runs, 1),
        "iar_by_reason": dict(iar_reasons),
        "directive_emission_rate": directives_emitted / max(total_runs, 1),
        "directive_follow_rate": (
            directive_followed / directive_eligible if directive_eligible > 0 else None
        ),
        "memory_ref_usage_rate": memory_ref_used / max(total_runs, 1),
        "cs_usage_rate": cs_ref_used / max(total_runs, 1),
        "mean_prompt_tokens": statistics.mean(prompt_tokens_list) if prompt_tokens_list else 0.0,
        "mean_completion_tokens": (
            statistics.mean(completion_tokens_list) if completion_tokens_list else 0.0
        ),
        "total_cost_usd": total_cost_usd,
        "latency_p50_ms": p50_lat,
        "latency_p95_ms": p95_lat,
        "scenarios": per_scenario_results,
    }

    target_dir = out_dir or (Path("runs") / "harness" / p_hash[:12])
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "report.json"
    md_path = target_dir / "report.md"

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    follow_str = (
        report["directive_follow_rate"]
        if report["directive_follow_rate"] is not None
        else "N/A"
    )
    md_lines = [
        f"# Prompt Harness Report (`{p_hash[:12]}`)",
        "",
        f"- **Model:** `{report['model']}`",
        (
            f"- **Scenarios:** {report['scenarios_count']} × "
            f"{report['samples_per_scenario']} samples = {report['total_runs']} runs"
        ),
        f"- **Parse OK (1st try):** {report['parse_ok_before_repair_rate']:.1%}",
        f"- **Parse OK (after repair):** {report['parse_ok_after_repair_rate']:.1%}",
        f"- **Parse failure rate:** {report['parse_failure_rate']:.1%}",
        f"- **Repair rate:** {report['repair_rate']:.1%}",
        f"- **IAR:** {report['iar_rate']:.1%} (`{report['iar_by_reason']}`)",
        f"- **Directive emission rate:** {report['directive_emission_rate']:.1%}",
        f"- **Directive follow rate:** {follow_str}",
        f"- **Memory ref usage rate:** {report['memory_ref_usage_rate']:.1%}",
        f"- **CS usage rate:** {report['cs_usage_rate']:.1%}",
        (
            f"- **Mean tokens:** {report['mean_prompt_tokens']:.0f} in / "
            f"{report['mean_completion_tokens']:.0f} out"
        ),
        (
            f"- **Latency:** p50 = {report['latency_p50_ms']:.0f} ms, "
            f"p95 = {report['latency_p95_ms']:.0f} ms"
        ),
        f"- **Total cost:** ${report['total_cost_usd']:.6f}",
        "",
        "## Scenario Breakdown",
        "",
        "| Scenario | Player | Action | Target | Parse OK | Invalid Reason |",
        "|---|---|---|---|---|---|",
    ]
    for sc_res in per_scenario_results:
        s0 = sc_res["samples"][0]
        md_lines.append(
            f"| `{sc_res['id']}` | `{sc_res['player_id']}` | `{s0['executed_action']}` | "
            f"`{s0['executed_target']}` | `{s0['parse_ok']}` | `{s0['invalid_reason']}` |"
        )

    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run WS3 20-scenario prompt harness.")
    parser.add_argument("--fake", action="store_true", help="Use FakeLLM(LegalXMLPolicy)")
    parser.add_argument("--samples", type=int, default=1, help="Samples per scenario")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory")
    args = parser.parse_args()

    report = asyncio.run(
        run_harness(use_fake=args.fake, samples=args.samples, out_dir=args.out_dir)
    )
    print(
        f"Harness complete ({report['total_runs']} runs): "
        f"parse_fail={report['parse_failure_rate']:.1%}, IAR={report['iar_rate']:.1%}"
    )


if __name__ == "__main__":
    main()
