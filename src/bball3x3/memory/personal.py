"""Bounded per-player personal memory built from templates without LLM calls (WS3 §3.7)."""

from __future__ import annotations

from collections import deque
from typing import Any

from bball3x3.schemas.state import GameState


class PersonalMemory:
    """Tracks the last ~8 relevant events for a single player using deterministic templates."""

    def __init__(self, player_id: str, maxlen: int = 8) -> None:
        self.player_id = player_id.upper()
        self.team = self.player_id[:1]
        self.maxlen = maxlen
        self._entries: deque[str] = deque(maxlen=maxlen)

    def reset(self) -> None:
        self._entries.clear()

    def lines(self) -> list[str]:
        return list(self._entries)

    def append_line(self, line: str) -> None:
        self._entries.append(line)

    def update(self, prev: GameState, state: GameState, payload: dict[str, Any]) -> None:
        """Inspect a resolved event payload and append a templated memory line if relevant."""
        e = payload.get("event_idx", state.event_idx)
        event = payload.get("event", {})
        actions: dict[str, str] = payload.get("actions", {})
        legalized = payload.get("legalized", {})
        holder: str | None = payload.get("holder")
        handler_action: str | None = payload.get("handler_action")
        my_act = actions.get(self.player_id, "HOLD")
        my_target = (
            legalized[self.player_id].target
            if self.player_id in legalized and legalized[self.player_id] is not None
            else None
        )

        # 1. Rebound event
        if payload.get("rebound"):
            winner = state.ball.holder
            if winner == self.player_id:
                kind = "offensive" if state.offense == self.team else "defensive"
                self._entries.append(f"E{e}: You secured the {kind} rebound.")
            elif winner is not None:
                self._entries.append(
                    f"E{e}: {winner} secured the rebound (ball at {state.ball.pos})."
                )
            return

        # 2. Shot event
        if handler_action == "SHOOT" and holder is not None:
            pts = event.get("points") or (
                2 if prev.players[holder].pos[1] >= 7 else 1
            )
            pos = prev.players[holder].pos
            if event.get("scored"):
                if holder == self.player_id:
                    self._entries.append(
                        f"E{e}: Your {pts}-pt shot from {pos} made (+{pts})."
                    )
                else:
                    scoring_team = event.get("scoring_team", holder[:1])
                    self._entries.append(
                        f"E{e}: Team {scoring_team} scored {pts} pt ({holder} from {pos})."
                    )
            else:
                primary_def = next(
                    (
                        d
                        for d, m in prev.matchups.items()
                        if m == holder and prev.players[d].team != prev.players[holder].team
                    ),
                    None,
                )
                contest_str = f" (contested by {primary_def})" if primary_def else ""
                if holder == self.player_id:
                    self._entries.append(
                        f"E{e}: Your {pts}-pt shot from {pos} missed{contest_str}."
                    )
                else:
                    self._entries.append(
                        f"E{e}: {holder}'s shot from {pos} missed{contest_str}."
                    )
            return

        # 3. Pass event
        if handler_action == "PASS" and holder is not None:
            pass_target = (
                legalized[holder].target if holder in legalized else None
            )
            if event.get("turnover"):
                reason = event.get("possession_reason", "TURNOVER")
                if reason == "STEAL" and state.ball.holder:
                    thief = state.ball.holder
                    if holder == self.player_id:
                        self._entries.append(
                            f"E{e}: Your pass to {pass_target} was stolen by {thief}."
                        )
                    elif thief == self.player_id:
                        self._entries.append(
                            f"E{e}: You stole {holder}'s pass intended for {pass_target}."
                        )
                    else:
                        self._entries.append(
                            f"E{e}: {thief} stole the ball from {holder}."
                        )
                else:
                    if holder == self.player_id:
                        self._entries.append(
                            f"E{e}: Your pass to {pass_target} went out of bounds."
                        )
                    else:
                        self._entries.append(
                            f"E{e}: {holder} committed a pass turnover ({reason})."
                        )
            else:
                new_holder = state.ball.holder
                if holder == self.player_id:
                    self._entries.append(
                        f"E{e}: You passed to {new_holder} — completed."
                    )
                elif new_holder == self.player_id:
                    self._entries.append(
                        f"E{e}: {holder} passed to you at {state.players[self.player_id].pos}."
                    )
                elif holder[:1] == self.team:
                    self._entries.append(
                        f"E{e}: {holder} passed to {new_holder} — completed."
                    )
            return

        # 4. Drive event
        if handler_action == "DRIVE" and holder is not None:
            if event.get("turnover"):
                thief = state.ball.holder
                if holder == self.player_id:
                    self._entries.append(
                        f"E{e}: You were stripped on the drive by {thief}."
                    )
                elif thief == self.player_id:
                    self._entries.append(
                        f"E{e}: You stripped {holder} on the drive."
                    )
                else:
                    self._entries.append(
                        f"E{e}: {thief} stripped {holder} on the drive."
                    )
                return
            if holder == self.player_id:
                new_pos = state.players[self.player_id].pos
                if new_pos != prev.players[self.player_id].pos:
                    self._entries.append(f"E{e}: You drove to {new_pos}.")
                else:
                    self._entries.append(f"E{e}: Your drive was stopped at {new_pos}.")
                return

        # 5. Shot clock violation
        if event.get("possession_reason") == "SHOT_CLOCK":
            self._entries.append(
                f"E{e}: Team {prev.offense} committed a shot-clock violation."
            )
            return

        # 6. Clear or player's own off-ball / defensive action
        if handler_action == "CLEAR" and holder == self.player_id:
            self._entries.append(
                f"E{e}: You cleared the ball to {state.players[self.player_id].pos}."
            )
        elif my_act != "HOLD":
            t_suffix = f" -> {my_target}" if my_target else ""
            self._entries.append(
                f"E{e}: You executed {my_act}{t_suffix} at {state.players[self.player_id].pos}."
            )
