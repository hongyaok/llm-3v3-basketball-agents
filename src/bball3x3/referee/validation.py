from dataclasses import dataclass

from ..schemas.referee import ContactEvent, RefereeDecision, RefereeState
from ..schemas.state import BallState, PlayerState
from .base import Referee
from .rule_referee import foul

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
        current_event={"actions": actions},
        contact_event=ContactEvent(
            contact_detected=contact_type is not None,
            players_involved=list(involved),
            contact_type=contact_type,
            details={"trigger_actions": actions},
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
            make_state(**drive),
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
            make_state(**screen, moved=(screener,)),
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
        got = await referee.judge(case.state)
        hits.append(_matches(got, case.expected))
        if not case.state.contact_event.contact_detected:
            false_calls.append(got.call != "NONE")
    return {
        "accuracy": sum(hits) / len(hits),
        "false_call_rate": sum(false_calls) / len(false_calls) if false_calls else 0.0,
    }
