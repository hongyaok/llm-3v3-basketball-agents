"""Local Phase A referee cases, evaluation, and optional game fuzzing."""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..schemas.referee import ContactEvent, RefereeDecision, RefereeState
from ..schemas.state import BallState, PlayerState
from .base import Referee
from .rule_referee import DEFAULT_CALL_PROBS, RuleBasedReferee, foul

DEFAULT_CASES = Path(__file__).with_name("validation_cases.jsonl")

POSITIONS = {
    "A1": (7, 6),
    "A2": (3, 4),
    "A3": (11, 4),
    "B1": (7, 5),
    "B2": (4, 4),
    "B3": (10, 4),
}
PAIRS = [("A1", "B1"), ("A2", "B2"), ("A3", "B3"), ("B1", "A1"), ("B2", "A2")]
SCREEN_VICTIMS = {"A2": "B2", "A3": "B3", "B2": "A2"}


@dataclass(frozen=True)
class RefereeCase:
    name: str
    state: RefereeState
    expected: RefereeDecision


# moved players get a prev_pos one cell away
def make_state(
    *,
    offense: str = "A",
    handler: str | None = None,
    actions: dict[str, str] | None = None,
    contact_type: str | None = None,
    involved: tuple[str, ...] = (),
    moved: tuple[str, ...] = (),
    loose: bool = False,
    event: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> RefereeState:
    handler = None if loose else handler or f"{offense}1"
    actions = actions or {}
    players = {
        pid: PlayerState(
            id=pid,
            team=pid[0],
            pos=pos,
            prev_pos=(pos[0], pos[1] + 1) if pid in moved else pos,
            has_ball=pid == handler,
        )
        for pid, pos in POSITIONS.items()
    }
    defense = "B" if offense == "A" else "A"
    ball = BallState(
        status="LOOSE" if loose else "HELD",
        pos=(7, 2) if loose else POSITIONS[handler],
        holder=handler,
    )
    return RefereeState(
        possession=offense,
        ball_handler=handler,
        players=players,
        matchups={f"{defense}{i}": f"{offense}{i}" for i in (1, 2, 3)},
        ball=ball,
        current_event={"actions": actions, **(event or {})},
        contact_event=ContactEvent(
            contact_detected=contact_type is not None,
            players_involved=list(involved),
            contact_type=contact_type,
            details={"trigger_actions": actions, **(details or {})},
        ),
    )


def _contact_cases() -> list[RefereeCase]:
    cases = []
    for handler, defender in PAIRS:
        drive = dict(
            offense=handler[0],
            handler=handler,
            actions={handler: "DRIVE", defender: "DEFEND"},
            contact_type="BODY_CONTACT_DRIVE",
            involved=(handler, defender),
        )
        cases.append(RefereeCase(
            f"drive_block_{handler}",
            make_state(**drive, moved=(defender,)),
            foul("DEFENSIVE_FOUL", defender, handler),
        ))
        cases.append(RefereeCase(
            f"drive_charge_{handler}",
            make_state(**drive, event={"offensive_contact": True}),
            foul("OFFENSIVE_FOUL", handler, defender),
        ))
        for act, kind in (("HOLD", "DEFENSIVE_FOUL"), ("SHOOT", "SHOOTING_FOUL")):
            cases.append(RefereeCase(
                f"reach_{act.lower()}_{handler}",
                make_state(
                    offense=handler[0],
                    handler=handler,
                    actions={handler: act, defender: "STEAL_ATTEMPT"},
                    contact_type="REACH",
                    involved=(defender, handler),
                ),
                foul(kind, defender, handler),
            ))

    for screener, victim in SCREEN_VICTIMS.items():
        screen = dict(
            offense=screener[0],
            actions={screener: "SCREEN"},
            contact_type="SCREEN_CONTACT",
            involved=(screener,),
        )
        cases.append(RefereeCase(
            f"screen_moving_{screener}",
            make_state(**screen, moved=(screener,), details={"contact_recipient": victim}),
            foul("OFFENSIVE_FOUL", screener, victim),
        ))
        cases.append(RefereeCase(
            f"screen_set_{screener}", make_state(**screen), RefereeDecision()
        ))

    rebounds = [
        ("A2", "CRASH_BOARDS", "B2", "BOX_OUT", foul("LOOSE_BALL_FOUL", "A2", "B2")),
        ("B3", "CRASH_BOARDS", "A3", "BOX_OUT", foul("LOOSE_BALL_FOUL", "B3", "A3")),
        ("A2", "CRASH_BOARDS", "B2", "CRASH_BOARDS", RefereeDecision()),
        ("A3", "BOX_OUT", "B3", "BOX_OUT", RefereeDecision()),
    ]
    for p, p_act, q, q_act, expected in rebounds:
        cases.append(RefereeCase(
            f"rebound_{p}_{p_act.lower()}_{q}_{q_act.lower()}",
            make_state(
                loose=True,
                actions={p: p_act, q: q_act},
                contact_type="LOOSE_BALL",
                involved=(p, q),
            ),
            expected,
        ))
    return cases


def _clean_cases() -> list[RefereeCase]:
    setups = [
        ("drive", dict(actions={"A1": "DRIVE", "B1": "DEFEND"})),
        ("shot_contested", dict(actions={"A1": "SHOOT", "B1": "CONTEST"})),
        ("pass", dict(actions={"A1": "PASS"})),
        ("steal_miss", dict(actions={"A1": "HOLD", "B1": "STEAL_ATTEMPT"})),
        ("screen_moving", dict(actions={"A2": "SCREEN"}, moved=("A2",))),
        ("drive_b", dict(offense="B", actions={"B1": "DRIVE", "A1": "DEFEND"}, moved=("A1",))),
        ("shot_b", dict(offense="B", actions={"B1": "SHOOT"})),
        ("rebound", dict(loose=True, actions={"A2": "CRASH_BOARDS", "B2": "BOX_OUT"})),
        ("dribble", dict(actions={"A1": "DRIBBLE_MOVE"}, moved=("A1",))),
        ("cut_b", dict(offense="B", actions={"B2": "CUT"}, moved=("B2",))),
    ]
    return [
        RefereeCase(f"clean_{name}", make_state(**kwargs), RefereeDecision())
        for name, kwargs in setups
    ]


CASES = _contact_cases() + _clean_cases()


def _matches(got: RefereeDecision, want: RefereeDecision) -> bool:
    fields = ("call", "foul_type", "violation_type", "offender", "fouled_player")
    return all(getattr(got, f) == getattr(want, f) for f in fields)


async def score(referee: Referee, cases: list[RefereeCase] = CASES) -> dict[str, float]:
    hits = []
    false_calls = []
    for case in cases:
        got = referee.judge(case.state)
        hits.append(_matches(got, case.expected))
        if not case.state.contact_event.contact_detected:
            false_calls.append(got.call != "NONE")
    return {
        "accuracy": sum(hits) / len(hits),
        "false_call_rate": sum(false_calls) / len(false_calls) if false_calls else 0.0,
    }


def load_cases(path: str | Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    """Read the checked-in labelled cases, preserving their JSONL order."""
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                case = json.loads(line)
                if not isinstance(case, dict):
                    raise ValueError("case must be a JSON object")
                name = case.get("id")
                if not isinstance(name, str) or not name or name in seen:
                    raise ValueError("case needs a unique, non-empty id")
                if not isinstance(case.get("event"), dict):
                    raise ValueError("case event must be an object")
                if not isinstance(case.get("expected"), dict):
                    raise ValueError("case expected call must be an object")
                seen.add(name)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            cases.append(case)
    if not cases:
        raise ValueError(f"{path}: no validation cases")
    return cases


def _state_from_case(case: dict[str, Any]) -> RefereeState:
    possession = case.get("possession", "A")
    handler = case.get("holder", f"{possession}1")
    contact_type = case.get("contact_type")
    ball_status = case.get("ball_status", "LOOSE" if contact_type == "LOOSE_BALL" else "HELD")
    ball_holder = handler if ball_status == "HELD" else None
    players = {
        pid: PlayerState(
            id=pid, team=pid[0], pos=pos, prev_pos=pos, has_ball=pid == ball_holder,
        )
        for pid, pos in POSITIONS.items()
    }
    return RefereeState(
        possession=possession,
        ball_handler=handler,
        players=players,
        matchups={f"{'B' if possession == 'A' else 'A'}{i}": f"{possession}{i}"
                  for i in (1, 2, 3)},
        ball=BallState(status=ball_status, pos=POSITIONS.get(ball_holder, (7, 2)),
                       holder=ball_holder),
        current_event=case["event"],
        contact_event=ContactEvent(
            contact_detected=contact_type is not None,
            contact_type=contact_type,
            players_involved=case.get("players", []),
            details=case.get("details", {}),
        ),
    )


def _count(correct: int, total: int) -> dict[str, int | float | None]:
    return {"correct": correct, "total": total, "rate": correct / total if total else None}


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Score exact calls with contact probabilities fixed at one."""
    referee = RuleBasedReferee(seed=0, call_probs={kind: 1.0 for kind in DEFAULT_CALL_PROBS})
    correct = 0
    clean_count = 0
    clean_false_calls = 0
    by_contact: dict[str, dict[str, int]] = {}
    mismatches: list[dict[str, Any]] = []
    for case in cases:
        got = referee.judge(_state_from_case(case))
        expected = RefereeDecision.model_validate(case["expected"])
        matched = _matches(got, expected)
        correct += matched
        kind = case.get("contact_type") or "NO_CONTACT"
        tally = by_contact.setdefault(kind, {"correct": 0, "total": 0})
        tally["correct"] += matched
        tally["total"] += 1
        if kind == "NO_CONTACT":
            clean_count += 1
            clean_false_calls += got.call != "NONE"
        if not matched:
            mismatches.append({
                "id": case["id"],
                "expected": expected.model_dump(exclude_none=True),
                "actual": got.model_dump(exclude_none=True),
            })
    return {
        "cases": len(cases),
        "contact_cases": len(cases) - clean_count,
        "no_contact_cases": clean_count,
        "accuracy": _count(correct, len(cases)),
        "no_contact_false_call_rate": {
            "false_calls": clean_false_calls,
            "total": clean_count,
            "rate": clean_false_calls / clean_count if clean_count else None,
        },
        "by_contact_type": {
            kind: _count(values["correct"], values["total"])
            for kind, values in sorted(by_contact.items())
        },
        "mismatches": mismatches,
    }


def run_fuzz_games(games: int) -> dict[str, int]:
    """Play deterministic local games and count broken invariants or truncations."""
    if games < 0:
        raise ValueError("games must be non-negative")
    from bball3x3.config import SimulationConfig
    from bball3x3.engine.loop import play_heuristic_game

    max_events = 1500
    config = SimulationConfig()
    results = [
        play_heuristic_game(seed=seed, config=config, max_events=max_events)
        for seed in range(games)
    ]
    return {
        "games": games,
        "events": sum(result["events"] for result in results),
        "invariant_violations": sum(len(result["violations"]) for result in results),
        "truncated_games": sum(result["events"] >= max_events for result in results),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the WS5 Phase A referee")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--fuzz-games", type=int, default=0)
    args = parser.parse_args(argv)
    report = evaluate_cases(load_cases(args.cases))
    if args.fuzz_games:
        report["fuzz_games"] = run_fuzz_games(args.fuzz_games)
    print(json.dumps(report, sort_keys=True))
    fuzz = report.get("fuzz_games")
    return int(
        bool(report["mismatches"])
        or bool(fuzz and (fuzz["invariant_violations"] or fuzz["truncated_games"]))
    )
