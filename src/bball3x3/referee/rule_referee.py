import math
from collections.abc import Mapping

import numpy as np
from numpy.random import SeedSequence

from ..schemas.referee import (
    OBJECTIVE_VIOLATIONS,
    FoulType,
    RefereeDecision,
    RefereeState,
)

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


def _opponents(state: RefereeState, offender: object, fouled: object) -> bool:
    return (
        isinstance(offender, str)
        and isinstance(fouled, str)
        and offender in state.players
        and fouled in state.players
        and state.players[offender].team != state.players[fouled].team
    )


class RuleBasedReferee:
    """Seeded Phase A judge over explicit event and contact evidence."""

    def __init__(
        self,
        seed: int = 0,
        call_probs: Mapping[str, float] | None = None,
        *,
        foul_probabilities: Mapping[str, float] | None = None,
    ) -> None:
        if call_probs is not None and foul_probabilities is not None:
            raise ValueError("Specify only one set of foul probabilities.")
        overrides = foul_probabilities if foul_probabilities is not None else call_probs
        self.call_probs = {**DEFAULT_CALL_PROBS, **(overrides or {})}
        for kind, probability in self.call_probs.items():
            if (
                kind not in DEFAULT_CALL_PROBS
                or isinstance(probability, bool)
                or not isinstance(probability, (int, float))
                or not math.isfinite(probability)
                or not 0.0 <= probability <= 1.0
            ):
                raise ValueError(f"Invalid foul probability for {kind}: {probability!r}")
        self._rng = np.random.default_rng(SeedSequence(seed, spawn_key=(REFEREE_SPAWN_KEY,)))

    def judge(self, state: RefereeState) -> RefereeDecision:
        event = state.current_event
        event_type = event.get("event_type")
        if (
            event.get("objective_violation") is True
            or isinstance(event_type, str) and event_type in OBJECTIVE_VIOLATIONS
        ):
            return RefereeDecision()

        violation = event.get("judgement_violation")
        offender = event.get("offender")
        if (
            isinstance(violation, str)
            and violation in {"GOALTENDING", "BASKET_INTERFERENCE", "STALLING"}
            and isinstance(offender, str)
            and offender in state.players
        ):
            return RefereeDecision(
                call="VIOLATION", violation_type=violation, offender=offender,
            )
        if event.get("technical_conduct") is True and isinstance(offender, str):
            if offender in state.players:
                return foul("TECHNICAL", offender, None)

        contact = state.contact_event
        if not contact.contact_detected or state.ball.status == "DEAD":
            return RefereeDecision()
        if event.get("unsportsmanlike_contact") is True:
            pair = self._contact_pair(state)
            if pair is not None:
                return foul("UNSPORTSMANLIKE", *pair)
        candidate = self._candidate(state)
        if candidate is None:
            return RefereeDecision()
        if self._rng.random() >= self.call_probs.get(contact.contact_type or "", 0.0):
            return RefereeDecision()
        return candidate

    def decide(self, state: RefereeState) -> RefereeDecision:
        """Retain the original Phase A convenience method."""
        return self.judge(state)

    @staticmethod
    def _contact_pair(state: RefereeState) -> tuple[str, str] | None:
        contact = state.contact_event
        players = contact.players_involved
        event = state.current_event
        details = contact.details
        kind = contact.contact_type
        if kind == "BODY_CONTACT_DRIVE" and len(players) >= 2:
            pair = (players[1], players[0])
        elif kind == "REACH" and len(players) >= 2:
            pair = (players[0], players[1])
        elif kind == "SCREEN_CONTACT" and players:
            recipient = details.get("contact_recipient", details.get("fouled_player"))
            pair = (players[0], recipient or (players[1] if len(players) > 1 else None))
        elif kind == "LOOSE_BALL":
            pair = (
                details.get("contact_initiator", details.get("offender", event.get("offender"))),
                details.get(
                    "contact_recipient",
                    details.get("fouled_player", event.get("fouled_player")),
                ),
            )
        else:
            return None
        if _opponents(state, *pair):
            return pair
        return None

    def _candidate(self, state: RefereeState) -> RefereeDecision | None:
        contact = state.contact_event
        involved = contact.players_involved
        actions = contact.details.get("trigger_actions", {})
        if not isinstance(actions, Mapping):
            actions = {}
        event = state.current_event
        handler = state.ball_handler
        others = [pid for pid in involved if pid != handler and pid in state.players]

        if contact.contact_type == "BODY_CONTACT_DRIVE" and handler in involved and others:
            defender = others[0]
            if not _opponents(state, handler, defender):
                return None
            if event.get("offensive_contact") is True:
                return foul("OFFENSIVE_FOUL", handler, defender)
            if event.get("was_shooting") is True or state.ball.status == "IN_SHOT":
                return foul("SHOOTING_FOUL", defender, handler)
            return foul("DEFENSIVE_FOUL", defender, handler)

        if contact.contact_type == "REACH" and handler in involved and others:
            defender = others[0]
            if not _opponents(state, defender, handler):
                return None
            shooting = (
                event.get("was_shooting") is True
                or state.ball.status == "IN_SHOT"
                or actions.get(handler) == "SHOOT"
            )
            return foul("SHOOTING_FOUL" if shooting else "DEFENSIVE_FOUL", defender, handler)

        if contact.contact_type == "SCREEN_CONTACT":
            pair = self._contact_pair(state)
            if pair is not None:
                return foul("OFFENSIVE_FOUL", *pair)

        if contact.contact_type == "LOOSE_BALL":
            pair = self._contact_pair(state)
            if pair is not None:
                return foul("LOOSE_BALL_FOUL", *pair)
            for crasher in involved:
                for boxer in involved:
                    if (
                        actions.get(crasher) == "CRASH_BOARDS"
                        and actions.get(boxer) == "BOX_OUT"
                        and _opponents(state, crasher, boxer)
                    ):
                        return foul("LOOSE_BALL_FOUL", crasher, boxer)

        return None
