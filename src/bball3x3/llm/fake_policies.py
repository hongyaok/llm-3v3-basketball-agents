"""Scripted and state-aware policies for FakeLLM (WS3 §3.1 & §4)."""

from __future__ import annotations

import re

from bball3x3.llm.base import Messages

_PLAYER_RE = re.compile(r"^Player:\s*([AB]\d+)", re.MULTILINE)
_ROLE_RE = re.compile(r"^Role:\s*(\w+)", re.MULTILINE)
_LEGAL_BLOCK_RE = re.compile(
    r"\[LEGAL ACTIONS\]\n(.*?)(?:\n\n|\Z)", re.DOTALL
)
_DIRECTIVE_RE = re.compile(
    r"\[action\s+to=([AB]\d+)\s+act=(\w+)(?:\s+target=([^\s\]]+))?\]",
    re.IGNORECASE,
)
_MEM_ENTRY_RE = re.compile(r"^(M\d+):\s*([AB]\d+)", re.MULTILINE)


def _choose_action_from_prompt(user_text: str) -> tuple[str, str, str | None, str | None]:
    """Return (player_id, action, target, memory_ref) parsed from the observation prompt."""
    p_match = _PLAYER_RE.search(user_text)
    pid = p_match.group(1) if p_match else "A1"
    r_match = _ROLE_RE.search(user_text)
    role = r_match.group(1) if r_match else "BALL_HANDLER"

    legal_block = _LEGAL_BLOCK_RE.search(user_text)
    legal_lines = (
        [
            line.lstrip("- ").strip()
            for line in legal_block.group(1).strip().splitlines()
            if line.strip() and line.strip() != "none"
        ]
        if legal_block
        else ["HOLD"]
    )

    legal_map: dict[str, str | None] = {}
    for line in legal_lines:
        if "(" in line:
            act_name = line.split("(", 1)[0].strip()
            hint_part = line.split(":", 1)[1].rstrip(")").strip()
            first_opt = hint_part.split("|")[0].strip()
            legal_map[act_name] = "PAINT" if first_opt == "zone" else first_opt
        else:
            legal_map[line.strip()] = None

    # Check if there is a directive addressed to pid that is legal
    for d_match in _DIRECTIVE_RE.finditer(user_text):
        to_pid, d_act, d_target = (
            d_match.group(1).upper(),
            d_match.group(2).upper(),
            d_match.group(3),
        )
        if to_pid == pid and d_act in legal_map:
            clean_t = (
                None
                if not d_target or d_target.upper() == "NONE"
                else d_target.upper()
            )
            return pid, d_act, clean_t or legal_map[d_act], None

    mem_match = _MEM_ENTRY_RE.search(user_text)
    mem_ref = mem_match.group(1) if mem_match else None

    if "CLEAR" in legal_map:
        return pid, "CLEAR", None, mem_ref
    if role == "BALL_HANDLER":
        for candidate in ("SHOOT", "DRIVE", "PASS", "HOLD"):
            if candidate in legal_map:
                return pid, candidate, legal_map[candidate], mem_ref
    elif role == "OFF_BALL":
        for candidate in ("CUT", "SPOT_UP", "MOVE", "HOLD"):
            if candidate in legal_map:
                return pid, candidate, legal_map[candidate], mem_ref
    elif role == "DEFENSE":
        for candidate in ("CONTEST", "DEFEND", "HOLD"):
            if candidate in legal_map:
                return pid, candidate, legal_map[candidate], mem_ref
    elif role == "REBOUND":
        for candidate in ("CRASH_BOARDS", "BOX_OUT", "HOLD"):
            if candidate in legal_map:
                return pid, candidate, legal_map[candidate], None

    first_act = next(iter(legal_map), "HOLD")
    return pid, first_act, legal_map.get(first_act), mem_ref


class LegalXMLPolicy:
    """Deterministic callable policy for FakeLLM that always emits legal XML."""

    def __init__(self, *, emit_coordination: bool = True) -> None:
        self.emit_coordination = emit_coordination
        self.calls = 0

    def __call__(self, messages: Messages) -> str:
        self.calls += 1
        # If this is a repair re-ask, the original observation is in messages[1]
        user_msg = next(
            (
                m["content"]
                for m in messages
                if m["role"] == "user" and "[OWN STATE]" in m["content"]
            ),
            messages[-1]["content"],
        )
        sys_msg = messages[0]["content"] if messages else ""
        pid, act, target, mem_ref = _choose_action_from_prompt(user_msg)
        team = pid[:1]
        mate = f"{team}2" if pid != f"{team}2" else f"{team}3"

        target_attr = f' target="{target}"' if target else ' target="None"'
        mem_attr = f' memory_ref="{mem_ref}"' if mem_ref else ""
        lines = ["<RESPONSE>", f'  <ACTION type="{act}"{target_attr}{mem_attr}/>']

        if self.emit_coordination:
            if "Teammate messaging `<MESSAGES>` is disabled" not in user_msg:
                lines.append("  <MESSAGES>")
                if act in ("PASS", "DRIVE", "SHOOT"):
                    lines.append(
                        f"    <{pid}>[action to={mate} act=CUT target=PAINT] "
                        f"cut to the rim [/action]</{pid}>"
                    )
                else:
                    lines.append(f"    <{pid}>staying active on {act}</{pid}>")
                lines.append("  </MESSAGES>")

            if "[CAPTAIN ADDENDUM]" in sys_msg:
                lines.append('  <CAPTAIN_CALL maintain="false">')
                lines.append(
                    f"    <{pid}><c>[tactic cs=None] "
                    f"space the floor and attack [/tactic]</c></{pid}>"
                )
                lines.append(
                    f"    <{pid}><c>[action to={mate} act=SPOT_UP target=LEFT_CORNER] "
                    f"spot up left corner [/action]</c></{pid}>"
                )
                lines.append("  </CAPTAIN_CALL>")

        lines.append(f"  <RATIONALE>Executing legal {act} for {pid}.</RATIONALE>")
        lines.append("</RESPONSE>")
        return "\n".join(lines)


class FaultInjectingPolicy:
    """Wraps a valid policy and injects malformed outputs on selected calls."""

    def __init__(
        self,
        base_policy: LegalXMLPolicy | None = None,
        *,
        fail_every_n_decisions: int = 0,
        recover_on_repair: bool = True,
    ) -> None:
        self.base = base_policy or LegalXMLPolicy()
        self.fail_every_n_decisions = fail_every_n_decisions
        self.recover_on_repair = recover_on_repair
        self.decision_calls = 0

    def __call__(self, messages: Messages) -> str:
        is_repair = len(messages) > 2
        if is_repair:
            if self.recover_on_repair:
                return self.base(messages)
            return "still malformed output with no XML tags at all"

        self.decision_calls += 1
        if (
            self.fail_every_n_decisions > 0
            and self.decision_calls % self.fail_every_n_decisions == 0
        ):
            return "malformed output missing response and action tags"
        return self.base(messages)
