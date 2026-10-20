"""XML and JSON I/O for LLM player agents (WS3 §3.4)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, get_args
from xml.sax.saxutils import escape as xml_escape

from lxml import etree

from bball3x3.engine.actions import ALL_ACTIONS, NO_TARGET_ACTIONS
from bball3x3.schemas.agent import AgentOutput
from bball3x3.schemas.memory import CSProposal, MemoryCategory, MemoryProposal
from bball3x3.schemas.messages import CaptainCall, Directive, Message

VALID_MEMORY_CATEGORIES: frozenset[str] = frozenset(get_args(MemoryCategory))
DEFAULT_ROSTER_IDS: frozenset[str] = frozenset({"A1", "A2", "A3", "B1", "B2", "B3"})

_CODE_FENCE_RE = re.compile(r"```(?:xml|json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_RESPONSE_OPEN_RE = re.compile(r"<RESPONSE\b[^>]*>", re.IGNORECASE)
_RESPONSE_CLOSE_RE = re.compile(r"</RESPONSE\s*>", re.IGNORECASE)

_KNOWN_TAG_RE = re.compile(
    r"^/?(?:RESPONSE|ACTION|MESSAGES|CAPTAIN_CALL|MEMORY_UPDATE|CS_UPDATE|RATIONALE|c|[AB]\d+|P\d+)\b[^>]*>",
    re.IGNORECASE,
)
_VALID_ENTITY_RE = re.compile(r"^&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")

# Inline [action ...] and [tactic ...] patterns
_ACTION_BLOCK_RE = re.compile(
    r"^\s*\[action(?P<attrs>[^\]]*)\](?P<body>.*?)(?:\[/action\]|\s*$)",
    re.IGNORECASE | re.DOTALL,
)
_TACTIC_BLOCK_RE = re.compile(
    r"^\s*\[tactic(?P<attrs>[^\]]*)\](?P<body>.*?)(?:\[/tactic\]|\s*$)",
    re.IGNORECASE | re.DOTALL,
)
_KV_ATTR_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s\]]+))')
_MEMORY_ID_RE = re.compile(r"^M\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class ParseContext:
    """Context used to validate IDs and enums when parsing agent outputs."""

    player_id: str = "A1"
    roster_ids: frozenset[str] = DEFAULT_ROSTER_IDS
    known_memory_ids: frozenset[str] | None = None
    known_cs_keys: frozenset[str] | None = None

    @property
    def team(self) -> str:
        return self.player_id[:1].upper()

    @property
    def teammates(self) -> frozenset[str]:
        team = self.team
        return frozenset(
            pid for pid in self.roster_ids if pid[:1].upper() == team and pid != self.player_id
        )

    @property
    def opponents(self) -> frozenset[str]:
        team = self.team
        return frozenset(pid for pid in self.roster_ids if pid[:1].upper() != team)


def _strip_fences_and_extract_response(raw_text: str) -> tuple[str | None, list[str]]:
    """Extract the first <RESPONSE>...</RESPONSE> block, tolerating missing </RESPONSE>."""
    warnings: list[str] = []
    # Check if there is a <RESPONSE> inside a code fence first, or in raw text
    candidates = [m.group(1) for m in _CODE_FENCE_RE.finditer(raw_text)]
    candidates.append(raw_text)

    for text in candidates:
        open_match = _RESPONSE_OPEN_RE.search(text)
        if not open_match:
            continue
        start = open_match.start()
        after_open = text[open_match.end() :]
        close_match = _RESPONSE_CLOSE_RE.search(after_open)
        if close_match:
            end = open_match.end() + close_match.end()
            return text[start:end], warnings
        # Missing closing tag: accept up to the end of the text
        cleaned_tail = _CODE_FENCE_RE.sub(r"\1", after_open).replace("```", "")
        warnings.append("WARN: missing </RESPONSE> closing tag; recovered to end of text")
        return text[start : open_match.end()] + cleaned_tail + "</RESPONSE>", warnings

    return None, warnings


def _escape_stray_chars(xml_text: str) -> str:
    """Escape stray '&' and '<' inside text nodes while preserving known XML tags."""
    out: list[str] = []
    i = 0
    n = len(xml_text)
    in_tag = False
    quote_char: str | None = None

    while i < n:
        ch = xml_text[i]
        if in_tag:
            if quote_char is not None:
                if ch == quote_char:
                    quote_char = None
                elif ch == "&" and not _VALID_ENTITY_RE.match(xml_text[i:]):
                    out.append("&amp;")
                    i += 1
                    continue
                elif ch == "<":
                    out.append("&lt;")
                    i += 1
                    continue
            else:
                if ch in ('"', "'"):
                    quote_char = ch
                elif ch == ">":
                    in_tag = False
            out.append(ch)
            i += 1
        else:
            if ch == "<":
                if _KNOWN_TAG_RE.match(xml_text[i + 1 :]):
                    in_tag = True
                    out.append(ch)
                else:
                    out.append("&lt;")
                i += 1
            elif ch == "&":
                if _VALID_ENTITY_RE.match(xml_text[i:]):
                    out.append(ch)
                else:
                    out.append("&amp;")
                i += 1
            else:
                out.append(ch)
                i += 1

    return "".join(out)


def _attr_ci(elem: etree._Element, name: str) -> str | None:
    """Case-insensitive attribute lookup."""
    target = name.lower()
    for k, v in elem.attrib.items():
        if k.lower() == target:
            return v
    return None


def _clean_nullable(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped.upper() in ("NONE", "NULL"):
        return None
    return stripped


def _parse_kv_attrs(attr_str: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _KV_ATTR_RE.finditer(attr_str):
        key = match.group(1).lower()
        val = match.group(2) or match.group(3) or match.group(4) or ""
        attrs[key] = val.strip()
    return attrs


def _parse_inline_message(
    raw_inner: str,
    sender: str,
    is_captain_channel: bool,
    ctx: ParseContext,
    errors: list[str],
) -> Message | None:
    text = raw_inner.strip()
    if not text:
        return None

    act_match = _ACTION_BLOCK_RE.match(text)
    if act_match:
        attr_str = act_match.group("attrs").strip()
        body = act_match.group("body").strip()
        if not attr_str:
            # Bare [action] with no attributes: kind="action", directive=None
            return Message(
                sender=sender,
                is_captain_channel=is_captain_channel,
                kind="action",
                text=body,
                directive=None,
                cs=None,
            )
        attrs = _parse_kv_attrs(attr_str)
        to_val = _clean_nullable(attrs.get("to"))
        act_val = _clean_nullable(attrs.get("act"))
        target_val = _clean_nullable(attrs.get("target"))

        if not to_val or not act_val:
            errors.append(f"WARN: malformed directive in [action {attr_str}] (missing to/act)")
            return None

        to_upper = to_val.upper()
        act_upper = act_val.upper()
        target_upper = target_val.upper() if target_val is not None else None

        if to_upper not in ctx.roster_ids or to_upper == sender:
            errors.append(f"WARN: invalid directive recipient to={to_upper!r}")
            return None
        if to_upper[:1] != sender[:1]:
            errors.append(
                f"WARN: directive recipient to={to_upper!r} is not a teammate of {sender}"
            )
            return None
        if act_upper not in ALL_ACTIONS:
            errors.append(f"WARN: unknown directive action act={act_upper!r}")
            return None

        return Message(
            sender=sender,
            is_captain_channel=is_captain_channel,
            kind="action",
            text=body,
            directive=Directive(to=to_upper, act=act_upper, target=target_upper),
            cs=None,
        )

    tac_match = _TACTIC_BLOCK_RE.match(text)
    if tac_match:
        attr_str = tac_match.group("attrs").strip()
        body = tac_match.group("body").strip()
        attrs = _parse_kv_attrs(attr_str) if attr_str else {}
        cs_val = _clean_nullable(attrs.get("cs"))
        if cs_val is not None and ctx.known_cs_keys is not None and cs_val not in ctx.known_cs_keys:
            errors.append(f"WARN: unknown cs key {cs_val!r} in [tactic]")
        return Message(
            sender=sender,
            is_captain_channel=is_captain_channel,
            kind="tactic",
            text=body,
            directive=None,
            cs=cs_val,
        )

    # Check if text starts with malformed [action or [tactic without closing ']'
    if text.lower().startswith("[action") or text.lower().startswith("[tactic"):
        errors.append(f"WARN: malformed inline tag in message: {text[:40]!r}")
        return None

    return Message(
        sender=sender,
        is_captain_channel=is_captain_channel,
        kind="info",
        text=text,
        directive=None,
        cs=None,
    )


def _extract_message_element(
    elem: etree._Element,
    default_captain_channel: bool,
    ctx: ParseContext,
    errors: list[str],
) -> Message | None:
    tag_upper = str(elem.tag).upper()
    is_captain = default_captain_channel
    sender = ctx.player_id.upper()

    if tag_upper in ctx.roster_ids:
        sender = tag_upper
    elif tag_upper == "C":
        is_captain = True
    else:
        errors.append(f"WARN: unexpected message element tag <{elem.tag}>")
        return None

    # Check for nested <c> wrapper
    c_child = next((ch for ch in elem if str(ch.tag).upper() == "C"), None)
    if c_child is not None:
        is_captain = True
        inner_text = "".join(c_child.itertext())
    else:
        inner_text = "".join(elem.itertext())

    return _parse_inline_message(inner_text, sender, is_captain, ctx, errors)


def parse_response(raw_text: str, ctx: ParseContext | None = None) -> AgentOutput:
    """Parse an LLM XML response into an AgentOutput following the WS3 error policy."""
    ctx = ctx or ParseContext()
    extracted, errors = _strip_fences_and_extract_response(raw_text)
    if extracted is None:
        return AgentOutput(
            action="HOLD",
            raw_text=raw_text,
            parse_ok=False,
            parse_errors=["FATAL: no <RESPONSE> block found"],
        )

    sanitized = _escape_stray_chars(extracted)
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(sanitized.encode("utf-8"), parser=parser)
    except Exception as exc:  # pragma: no cover - recover=True rarely raises
        return AgentOutput(
            action="HOLD",
            raw_text=raw_text,
            parse_ok=False,
            parse_errors=[f"FATAL: XML parse error: {exc}"],
        )

    if root is None or str(root.tag).upper() != "RESPONSE":
        return AgentOutput(
            action="HOLD",
            raw_text=raw_text,
            parse_ok=False,
            parse_errors=["FATAL: root element is not <RESPONSE>"],
        )

    action_elem = next(
        (ch for ch in root if isinstance(ch.tag, str) and ch.tag.upper() == "ACTION"),
        None,
    )
    if action_elem is None:
        return AgentOutput(
            action="HOLD",
            raw_text=raw_text,
            parse_ok=False,
            parse_errors=[*errors, "FATAL: missing <ACTION> element"],
        )

    raw_action = _clean_nullable(_attr_ci(action_elem, "type"))
    if not raw_action:
        return AgentOutput(
            action="HOLD",
            raw_text=raw_text,
            parse_ok=False,
            parse_errors=[*errors, "FATAL: <ACTION> missing non-empty type attribute"],
        )

    action = raw_action.upper()
    raw_target = _clean_nullable(_attr_ci(action_elem, "target"))
    target = raw_target.upper() if raw_target is not None else None
    if target is not None and action in NO_TARGET_ACTIONS:
        errors.append(f"WARN: target {target!r} ignored for {action}")
        target = None

    raw_mem_ref = _clean_nullable(_attr_ci(action_elem, "memory_ref"))
    memory_ref: list[str] | None = None
    if raw_mem_ref is not None:
        refs = [
            part.strip().upper()
            for part in raw_mem_ref.split(",")
            if _clean_nullable(part) is not None
        ]
        if refs:
            memory_ref = refs
            for ref in refs:
                if not _MEMORY_ID_RE.match(ref):
                    errors.append(f"WARN: invalid memory_ref format {ref!r}")
                elif ctx.known_memory_ids is not None and ref not in ctx.known_memory_ids:
                    errors.append(f"WARN: unknown memory_ref {ref!r}")

    messages: list[Message] = []
    captain_call: CaptainCall | None = None
    memory_update: MemoryProposal | None = None
    cs_update: CSProposal | None = None
    rationale: str | None = None

    for child in root:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.upper()
        if tag == "ACTION":
            continue
        elif tag == "MESSAGES":
            for msg_el in child:
                if not isinstance(msg_el.tag, str):
                    continue
                msg = _extract_message_element(msg_el, False, ctx, errors)
                if msg is not None:
                    messages.append(msg)
        elif tag == "CAPTAIN_CALL":
            maintain_attr = (_attr_ci(child, "maintain") or "false").strip().lower()
            maintain = maintain_attr == "true"
            tactic_msg: Message | None = None
            directives: list[Message] = []
            for call_el in child:
                if not isinstance(call_el.tag, str):
                    continue
                msg = _extract_message_element(call_el, True, ctx, errors)
                if msg is None:
                    continue
                if msg.kind == "tactic":
                    if tactic_msg is None:
                        tactic_msg = msg
                elif msg.kind == "action":
                    if msg.directive is not None:
                        directives.append(msg)
                    else:
                        errors.append("WARN: bare [action] inside <CAPTAIN_CALL> has no directive")
                elif tactic_msg is None:
                    tactic_msg = Message(
                        sender=msg.sender,
                        is_captain_channel=True,
                        kind="tactic",
                        text=msg.text,
                        directive=None,
                        cs=msg.cs,
                    )
            has_maintain_attr = "maintain" in {k.lower() for k in child.attrib}
            if maintain or tactic_msg is not None or directives or has_maintain_attr:
                captain_call = CaptainCall(
                    maintain=maintain,
                    tactic=tactic_msg,
                    directives=directives,
                )
        elif tag == "MEMORY_UPDATE":
            opp = (_clean_nullable(_attr_ci(child, "opponent")) or "").upper()
            cat = (_clean_nullable(_attr_ci(child, "category")) or "").lower()
            tend = _clean_nullable(_attr_ci(child, "tendency")) or _clean_nullable(
                "".join(child.itertext())
            )
            if not opp or opp not in ctx.roster_ids or opp[:1] == ctx.team:
                errors.append(f"WARN: invalid MEMORY_UPDATE opponent={opp!r}")
            elif cat not in VALID_MEMORY_CATEGORIES:
                errors.append(f"WARN: invalid MEMORY_UPDATE category={cat!r}")
            elif not tend:
                errors.append("WARN: empty MEMORY_UPDATE tendency")
            else:
                memory_update = MemoryProposal(opponent=opp, category=cat, tendency=tend)
        elif tag == "CS_UPDATE":
            side = (_clean_nullable(_attr_ci(child, "side")) or "").lower()
            opp_strat = _clean_nullable(_attr_ci(child, "opponent_strategy"))
            counter_strat = _clean_nullable(_attr_ci(child, "counter_strategy"))
            if side not in ("offense", "defense"):
                errors.append(f"WARN: invalid CS_UPDATE side={side!r}")
            elif not opp_strat or not counter_strat:
                errors.append("WARN: CS_UPDATE missing opponent_strategy or counter_strategy")
            else:
                cs_update = CSProposal(
                    side=side,  # type: ignore[arg-type]
                    opponent_strategy=opp_strat,
                    counter_strategy=counter_strat,
                )
        elif tag == "RATIONALE":
            rat_text = "".join(child.itertext()).strip()
            if rat_text:
                rationale = rat_text

    return AgentOutput(
        action=action,
        target=target,
        memory_ref=memory_ref,
        messages=messages,
        captain_call=captain_call,
        memory_update=memory_update,
        cs_update=cs_update,
        rationale=rationale,
        raw_text=raw_text,
        parse_ok=True,
        parse_errors=errors,
    )


def make_xml_parser(ctx: ParseContext | None = None):
    """Return a Parser[AgentOutput] callable for complete_with_repair.

    Only fatal parse errors are returned in the second tuple element so
    warnings and engine-level IAR issues never trigger a repair re-ask.
    """

    def _parse(text: str) -> tuple[AgentOutput, list[str]]:
        output = parse_response(text, ctx)
        if not output.parse_ok:
            fatal = [e for e in output.parse_errors if not e.startswith("WARN:")]
            return output, fatal or ["FATAL: parse failed"]
        return output, []

    return _parse


def _escape_attr(value: str) -> str:
    return xml_escape(value, {'"': "&quot;"})


def render_message(msg: Message, *, escape_xml: bool = False) -> str:
    """Render a single Message into the Code 1 teammate-view tag string."""
    body = xml_escape(msg.text) if escape_xml else msg.text
    if msg.kind == "action":
        if msg.directive is not None:
            t_str = msg.directive.target if msg.directive.target is not None else "None"
            header = f"[action to={msg.directive.to} act={msg.directive.act} target={t_str}]"
        else:
            header = "[action]"
        inner = f"{header} {body} [/action]" if body else f"{header}[/action]"
    elif msg.kind == "tactic":
        cs_str = msg.cs if msg.cs is not None else "None"
        header = f"[tactic cs={cs_str}]"
        inner = f"{header} {body} [/tactic]" if body else f"{header}[/tactic]"
    else:
        inner = body

    if msg.is_captain_channel:
        return f"<{msg.sender}><c>{inner}</c></{msg.sender}>"
    return f"<{msg.sender}>{inner}</{msg.sender}>"


def render_response(output: AgentOutput) -> str:
    """Render an AgentOutput into canonical XML."""
    lines = ["<RESPONSE>"]
    target_attr = f' target="{_escape_attr(output.target)}"' if output.target else ""
    mem_attr = (
        f' memory_ref="{_escape_attr(",".join(output.memory_ref))}"'
        if output.memory_ref
        else ""
    )
    lines.append(f'  <ACTION type="{_escape_attr(output.action)}"{target_attr}{mem_attr}/>')

    if output.messages:
        lines.append("  <MESSAGES>")
        for msg in output.messages:
            lines.append(f"    {render_message(msg, escape_xml=True)}")
        lines.append("  </MESSAGES>")

    if output.captain_call is not None:
        maintain_str = "true" if output.captain_call.maintain else "false"
        call_children: list[Message] = []
        if output.captain_call.tactic is not None:
            call_children.append(
                output.captain_call.tactic.model_copy(update={"is_captain_channel": True})
            )
        for d_msg in output.captain_call.directives:
            call_children.append(d_msg.model_copy(update={"is_captain_channel": True}))
        if call_children:
            lines.append(f'  <CAPTAIN_CALL maintain="{maintain_str}">')
            for c_msg in call_children:
                lines.append(f"    {render_message(c_msg, escape_xml=True)}")
            lines.append("  </CAPTAIN_CALL>")
        else:
            lines.append(f'  <CAPTAIN_CALL maintain="{maintain_str}"/>')

    if output.memory_update is not None:
        mu = output.memory_update
        lines.append(
            f'  <MEMORY_UPDATE opponent="{_escape_attr(mu.opponent)}" '
            f'category="{_escape_attr(mu.category)}" '
            f'tendency="{_escape_attr(mu.tendency)}"/>'
        )

    if output.cs_update is not None:
        cu = output.cs_update
        lines.append(
            f'  <CS_UPDATE side="{_escape_attr(cu.side)}" '
            f'opponent_strategy="{_escape_attr(cu.opponent_strategy)}" '
            f'counter_strategy="{_escape_attr(cu.counter_strategy)}"/>'
        )

    if output.rationale is not None:
        lines.append(f"  <RATIONALE>{xml_escape(output.rationale)}</RATIONALE>")

    lines.append("</RESPONSE>")
    return "\n".join(lines)


RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "agent_response",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type", "target", "memory_ref"],
                    "properties": {
                        "type": {"type": "string"},
                        "target": {"type": ["string", "null"]},
                        "memory_ref": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                        },
                    },
                },
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind", "text", "directive", "cs"],
                        "properties": {
                            "kind": {"type": "string", "enum": ["action", "tactic", "info"]},
                            "text": {"type": "string"},
                            "directive": {
                                "type": ["object", "null"],
                                "additionalProperties": False,
                                "required": ["to", "act", "target"],
                                "properties": {
                                    "to": {"type": "string"},
                                    "act": {"type": "string"},
                                    "target": {"type": ["string", "null"]},
                                },
                            },
                            "cs": {"type": ["string", "null"]},
                        },
                    },
                },
                "captain_call": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "required": ["maintain", "tactic", "cs", "directives"],
                    "properties": {
                        "maintain": {"type": "boolean"},
                        "tactic": {"type": ["string", "null"]},
                        "cs": {"type": ["string", "null"]},
                        "directives": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["to", "act", "target", "text"],
                                "properties": {
                                    "to": {"type": "string"},
                                    "act": {"type": "string"},
                                    "target": {"type": ["string", "null"]},
                                    "text": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "memory_update": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "required": ["opponent", "category", "tendency"],
                    "properties": {
                        "opponent": {"type": "string"},
                        "category": {"type": "string"},
                        "tendency": {"type": "string"},
                    },
                },
                "cs_update": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "required": ["side", "opponent_strategy", "counter_strategy"],
                    "properties": {
                        "side": {"type": "string"},
                        "opponent_strategy": {"type": "string"},
                        "counter_strategy": {"type": "string"},
                    },
                },
                "rationale": {"type": ["string", "null"]},
            },
        },
    },
}


def json_to_output(
    payload: str | dict[str, Any], ctx: ParseContext | None = None
) -> AgentOutput:
    """Convert JSON-mode response into AgentOutput and render canonical XML to raw_text."""
    ctx = ctx or ParseContext()
    raw_str = payload if isinstance(payload, str) else json.dumps(payload)
    if isinstance(payload, str):
        fenced = _CODE_FENCE_RE.search(payload)
        candidate = fenced.group(1).strip() if fenced else payload.strip()
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            return AgentOutput(
                action="HOLD",
                raw_text=raw_str,
                parse_ok=False,
                parse_errors=[f"FATAL: invalid JSON: {exc}"],
            )
    else:
        data = payload

    if not isinstance(data, dict):
        return AgentOutput(
            action="HOLD",
            raw_text=raw_str,
            parse_ok=False,
            parse_errors=["FATAL: JSON root must be an object"],
        )

    act_block = data.get("action")
    if isinstance(act_block, str):
        act_type = _clean_nullable(act_block)
        act_target = _clean_nullable(data.get("target"))
        raw_refs = data.get("memory_ref")
    elif isinstance(act_block, dict):
        act_type = _clean_nullable(act_block.get("type"))
        act_target = _clean_nullable(act_block.get("target"))
        raw_refs = act_block.get("memory_ref")
    else:
        act_type = None
        act_target = None
        raw_refs = None

    if not act_type:
        return AgentOutput(
            action="HOLD",
            raw_text=raw_str,
            parse_ok=False,
            parse_errors=["FATAL: JSON missing action.type"],
        )

    mem_refs: list[str] | None = None
    if isinstance(raw_refs, str):
        parts = [p.strip().upper() for p in raw_refs.split(",") if _clean_nullable(p)]
        mem_refs = parts or None
    elif isinstance(raw_refs, list):
        parts = [str(p).strip().upper() for p in raw_refs if _clean_nullable(str(p))]
        mem_refs = parts or None

    sender = ctx.player_id.upper()
    msgs: list[Message] = []
    for item in data.get("messages") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "info").lower()
        text = str(item.get("text") or "").strip()
        cs = _clean_nullable(item.get("cs"))
        dir_obj = item.get("directive")
        directive: Directive | None = None
        if isinstance(dir_obj, dict):
            to_v = _clean_nullable(dir_obj.get("to"))
            act_v = _clean_nullable(dir_obj.get("act"))
            t_v = _clean_nullable(dir_obj.get("target"))
            if to_v and act_v:
                directive = Directive(
                    to=to_v.upper(),
                    act=act_v.upper(),
                    target=t_v.upper() if t_v else None,
                )
        msgs.append(
            Message(
                sender=sender,
                is_captain_channel=bool(item.get("is_captain_channel", False)),
                kind=kind if kind in ("action", "tactic", "info") else "info",  # type: ignore[arg-type]
                text=text,
                directive=directive,
                cs=cs,
            )
        )

    cap_data = data.get("captain_call")
    cap_call: CaptainCall | None = None
    if isinstance(cap_data, dict):
        maintain = bool(cap_data.get("maintain", False))
        tactic_val = cap_data.get("tactic")
        cs_val = _clean_nullable(cap_data.get("cs"))
        tactic_msg: Message | None = None
        if isinstance(tactic_val, str) and tactic_val.strip():
            tactic_msg = Message(
                sender=sender,
                is_captain_channel=True,
                kind="tactic",
                text=tactic_val.strip(),
                cs=cs_val,
            )
        elif isinstance(tactic_val, dict):
            t_text = str(tactic_val.get("text") or "").strip()
            t_cs = _clean_nullable(tactic_val.get("cs")) or cs_val
            if t_text or t_cs:
                tactic_msg = Message(
                    sender=sender,
                    is_captain_channel=True,
                    kind="tactic",
                    text=t_text,
                    cs=t_cs,
                )
        cap_dirs: list[Message] = []
        for d_item in cap_data.get("directives") or []:
            if not isinstance(d_item, dict):
                continue
            d_dir = d_item.get("directive") if isinstance(d_item.get("directive"), dict) else d_item
            to_v = _clean_nullable(d_dir.get("to"))
            act_v = _clean_nullable(d_dir.get("act"))
            t_v = _clean_nullable(d_dir.get("target"))
            d_text = str(d_item.get("text") or "").strip()
            if to_v and act_v:
                cap_dirs.append(
                    Message(
                        sender=sender,
                        is_captain_channel=True,
                        kind="action",
                        text=d_text,
                        directive=Directive(
                            to=to_v.upper(),
                            act=act_v.upper(),
                            target=t_v.upper() if t_v else None,
                        ),
                    )
                )
        cap_call = CaptainCall(maintain=maintain, tactic=tactic_msg, directives=cap_dirs)

    mu_data = data.get("memory_update")
    mem_up: MemoryProposal | None = None
    if isinstance(mu_data, dict):
        opp = _clean_nullable(mu_data.get("opponent"))
        cat = _clean_nullable(mu_data.get("category"))
        tend = _clean_nullable(mu_data.get("tendency"))
        if opp and cat and tend:
            mem_up = MemoryProposal(opponent=opp.upper(), category=cat.lower(), tendency=tend)

    cu_data = data.get("cs_update")
    cs_up: CSProposal | None = None
    if isinstance(cu_data, dict):
        side = (_clean_nullable(cu_data.get("side")) or "offense").lower()
        opp_s = _clean_nullable(cu_data.get("opponent_strategy"))
        cnt_s = _clean_nullable(cu_data.get("counter_strategy"))
        if side in ("offense", "defense") and opp_s and cnt_s:
            cs_up = CSProposal(
                side=side,  # type: ignore[arg-type]
                opponent_strategy=opp_s,
                counter_strategy=cnt_s,
            )

    rat = _clean_nullable(data.get("rationale"))
    draft = AgentOutput(
        action=act_type.upper(),
        target=act_target.upper() if act_target else None,
        memory_ref=mem_refs,
        messages=msgs,
        captain_call=cap_call,
        memory_update=mem_up,
        cs_update=cs_up,
        rationale=rat,
    )
    canonical_xml = render_response(draft)
    # Run through parse_response so identical validation and warning rules apply
    return parse_response(canonical_xml, ctx)


def make_json_parser(ctx: ParseContext | None = None):
    """Return a Parser[AgentOutput] callable for JSON mode in complete_with_repair."""

    def _parse(text: str) -> tuple[AgentOutput, list[str]]:
        output = json_to_output(text, ctx)
        if not output.parse_ok:
            fatal = [e for e in output.parse_errors if not e.startswith("WARN:")]
            return output, fatal or ["FATAL: JSON parse failed"]
        return output, []

    return _parse
