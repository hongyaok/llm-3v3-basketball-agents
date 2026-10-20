import numpy as np
from numpy.random import SeedSequence

from ..schemas.referee import FoulType, RefereeDecision, RefereeState

# placeholder call rates per contact type, calibrated in the pilot
DEFAULT_CALL_PROBS = {
    "BODY_CONTACT_DRIVE": 0.5,
    "REACH": 0.6,
    "SCREEN_CONTACT": 0.7,
    "LOOSE_BALL": 0.4,
}

# outside the engine's spawn keys, so referee draws never shift engine outcomes
REFEREE_SPAWN_KEY = 1000


def foul(foul_type: FoulType, offender: str, fouled: str | None) -> RefereeDecision:
    return RefereeDecision(
        call="FOUL", offender=offender, fouled_player=fouled, foul_type=foul_type
    )


def _moved(state: RefereeState, pid: str) -> bool:
    player = state.players[pid]
    return player.pos != player.prev_pos


def _nearest_opponent(
    state: RefereeState, pid: str, pool: list[str] | None = None
) -> str | None:
    me = state.players[pid]
    rivals = [o for o in (pool or state.players) if state.players[o].team != me.team]
    if not rivals:
        return None

    def dist(o: str) -> tuple[int, str]:
        x, y = state.players[o].pos
        return (x - me.pos[0]) ** 2 + (y - me.pos[1]) ** 2, o

    return min(rivals, key=dist)


# judges contact the engine annotated, mostly returning NONE
class RuleBasedReferee:
    def __init__(self, seed: int, call_probs: dict[str, float] | None = None):
        self.call_probs = {**DEFAULT_CALL_PROBS, **(call_probs or {})}
        self._rng = np.random.default_rng(SeedSequence(seed, spawn_key=(REFEREE_SPAWN_KEY,)))

    async def judge(self, state: RefereeState) -> RefereeDecision:
        return self.decide(state)

    def decide(self, state: RefereeState) -> RefereeDecision:
        contact = state.contact_event
        if not contact.contact_detected or state.ball.status == "DEAD":
            return RefereeDecision()
        candidate = self._candidate(state)
        if candidate is None:
            return RefereeDecision()
        if self._rng.random() >= self.call_probs.get(contact.contact_type or "", 0.0):
            return RefereeDecision()
        return candidate

    def _candidate(self, state: RefereeState) -> RefereeDecision | None:
        contact = state.contact_event
        involved = contact.players_involved
        actions = contact.details.get("trigger_actions", {})
        handler = state.ball_handler
        others = [pid for pid in involved if pid != handler]

        if contact.contact_type == "BODY_CONTACT_DRIVE" and handler and others:
            defender = others[0]
            if _moved(state, defender):
                return foul("DEFENSIVE_FOUL", defender, handler)
            return foul("OFFENSIVE_FOUL", handler, defender)

        if contact.contact_type == "REACH" and handler and others:
            kind = "SHOOTING_FOUL" if actions.get(handler) == "SHOOT" else "DEFENSIVE_FOUL"
            return foul(kind, others[0], handler)

        if contact.contact_type == "SCREEN_CONTACT" and involved:
            screener = involved[0]
            if _moved(state, screener):
                return foul("OFFENSIVE_FOUL", screener, _nearest_opponent(state, screener))

        if contact.contact_type == "LOOSE_BALL":
            # crashing through an opponent's box-out is the foul
            for pid in sorted(involved):
                if actions.get(pid) != "CRASH_BOARDS":
                    continue
                boxer = _nearest_opponent(state, pid, involved)
                if boxer and actions.get(boxer) == "BOX_OUT":
                    return foul("LOOSE_BALL_FOUL", pid, boxer)

        return None
