"""Unit and property tests for WS3 XML/JSON I/O (src/bball3x3/agents/xml_io.py)."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bball3x3.agents.xml_io import (
    RESPONSE_JSON_SCHEMA,
    VALID_MEMORY_CATEGORIES,
    ParseContext,
    json_to_output,
    make_xml_parser,
    parse_response,
    render_message,
    render_response,
)
from bball3x3.engine.actions import ALL_ACTIONS
from bball3x3.schemas.agent import AgentOutput
from bball3x3.schemas.memory import CSProposal, MemoryProposal
from bball3x3.schemas.messages import Directive, Message

FULL_VALID_XML = """\
<RESPONSE>
  <ACTION type="PASS" target="A2" memory_ref="M01,M03"/>
  <MESSAGES>
    <A1>[action to=A3 act=SCREEN target=B1] set a screen on B1 for me [/action]</A1>
    <A1>[tactic cs=01] let's run pick and pop on the left [/tactic]</A1>
    <A1>B1 keeps gambling on steals</A1>
  </MESSAGES>
  <CAPTAIN_CALL maintain="false">
    <A1><c>[tactic cs=None] pick and roll on the left wing, A2 handles [/tactic]</c></A1>
    <A1><c>[action to=A3 act=SCREEN target=A2] screen for A2 [/action]</c></A1>
  </CAPTAIN_CALL>
  <MEMORY_UPDATE opponent="B1" category="defensive_tendency"
                 tendency="leaves passing lanes open on contested drives"/>
  <CS_UPDATE side="offense" opponent_strategy="B switches every screen"
             counter_strategy="slip the screen and cut to the rim"/>
  <RATIONALE>B1 is overplaying; A2 is open on the cut.</RATIONALE>
</RESPONSE>
"""


def test_parse_valid_full_response():
    ctx = ParseContext(
        player_id="A1",
        known_memory_ids=frozenset({"M01", "M02", "M03"}),
        known_cs_keys=frozenset({"01"}),
    )
    out = parse_response(FULL_VALID_XML, ctx)
    assert out.parse_ok is True
    assert out.parse_errors == []
    assert out.action == "PASS"
    assert out.target == "A2"
    assert out.memory_ref == ["M01", "M03"]
    assert len(out.messages) == 3

    m0, m1, m2 = out.messages
    assert m0.kind == "action"
    assert m0.directive == Directive(to="A3", act="SCREEN", target="B1")
    assert m0.text == "set a screen on B1 for me"
    assert m0.is_captain_channel is False

    assert m1.kind == "tactic"
    assert m1.cs == "01"
    assert m1.text == "let's run pick and pop on the left"

    assert m2.kind == "info"
    assert m2.text == "B1 keeps gambling on steals"

    assert out.captain_call is not None
    assert out.captain_call.maintain is False
    assert out.captain_call.tactic is not None
    assert out.captain_call.tactic.kind == "tactic"
    assert out.captain_call.tactic.cs is None
    assert out.captain_call.tactic.is_captain_channel is True
    assert len(out.captain_call.directives) == 1
    assert out.captain_call.directives[0].directive == Directive(
        to="A3", act="SCREEN", target="A2"
    )
    assert out.captain_call.directives[0].is_captain_channel is True

    assert out.memory_update == MemoryProposal(
        opponent="B1",
        category="defensive_tendency",
        tendency="leaves passing lanes open on contested drives",
    )
    assert out.cs_update == CSProposal(
        side="offense",
        opponent_strategy="B switches every screen",
        counter_strategy="slip the screen and cut to the rim",
    )
    assert out.rationale == "B1 is overplaying; A2 is open on the cut."


def test_parse_minimal_response():
    out = parse_response('<RESPONSE><ACTION type="shoot" target="None"/></RESPONSE>')
    assert out.parse_ok is True
    assert out.parse_errors == []
    assert out.action == "SHOOT"
    assert out.target is None
    assert out.memory_ref is None
    assert out.messages == []
    assert out.captain_call is None
    assert out.memory_update is None
    assert out.cs_update is None
    assert out.rationale is None


def test_surrounding_prose_and_code_fences():
    raw = (
        "Here is my decision:\n"
        "```xml\n"
        "<RESPONSE>\n"
        '  <ACTION type="DRIVE" target="LEFT"/>\n'
        "</RESPONSE>\n"
        "```\n"
        "Hope that works!"
    )
    out = parse_response(raw)
    assert out.parse_ok is True
    assert out.action == "DRIVE"
    assert out.target == "LEFT"


def test_missing_closing_response_tag_recovers():
    raw = '<RESPONSE>\n  <ACTION type="CUT" target="PAINT"/>\n  <RATIONALE>cut hard</RATIONALE>'
    out = parse_response(raw)
    assert out.parse_ok is True
    assert out.action == "CUT"
    assert out.target == "PAINT"
    assert out.rationale == "cut hard"
    assert any(e.startswith("WARN:") for e in out.parse_errors)


def test_stray_ampersand_and_less_than_in_text_nodes():
    raw = (
        "<RESPONSE>\n"
        '  <ACTION type="HOLD"/>\n'
        "  <MESSAGES>\n"
        "    <A1>pick & roll when clock < 4s & B1 < B2</A1>\n"
        "  </MESSAGES>\n"
        "  <RATIONALE>clock < 3 & paint is crowded</RATIONALE>\n"
        "</RESPONSE>"
    )
    out = parse_response(raw)
    assert out.parse_ok is True
    assert out.messages[0].text == "pick & roll when clock < 4s & B1 < B2"
    assert out.rationale == "clock < 3 & paint is crowded"


def test_unclosed_tactic_and_bare_action():
    raw = (
        "<RESPONSE>\n"
        '  <ACTION type="HOLD"/>\n'
        "  <MESSAGES>\n"
        "    <A1>[tactic cs=None] spread the floor and attack paint</A1>\n"
        "    <A1>[action] I am cutting now [/action]</A1>\n"
        "  </MESSAGES>\n"
        "</RESPONSE>"
    )
    out = parse_response(raw)
    assert out.parse_ok is True
    assert len(out.messages) == 2
    assert out.messages[0].kind == "tactic"
    assert out.messages[0].cs is None
    assert out.messages[0].text == "spread the floor and attack paint"
    assert out.messages[1].kind == "action"
    assert out.messages[1].directive is None
    assert out.messages[1].text == "I am cutting now"


def test_unknown_action_is_passed_through_not_fatal():
    raw = '<RESPONSE><ACTION type="SLAM_DUNK_360" target="B1"/></RESPONSE>'
    parser = make_xml_parser(ParseContext(player_id="A1"))
    out, fatal_errors = parser(raw)
    assert out.parse_ok is True
    assert fatal_errors == []
    assert out.action == "SLAM_DUNK_360"
    assert out.target == "B1"


def test_bad_memory_ref_and_malformed_optionals_produce_warnings_only():
    ctx = ParseContext(player_id="A1", known_memory_ids=frozenset({"M01"}))
    raw = (
        "<RESPONSE>\n"
        '  <ACTION type="SHOOT" memory_ref="M99"/>\n'
        "  <MESSAGES>\n"
        "    <A1>[action to=B1 act=SCREEN] bad recipient [/action]</A1>\n"
        "  </MESSAGES>\n"
        '  <MEMORY_UPDATE opponent="B1" category="not_a_category" tendency="foo"/>\n'
        "</RESPONSE>"
    )
    parser = make_xml_parser(ctx)
    out, fatal_errors = parser(raw)
    assert out.parse_ok is True
    assert fatal_errors == []
    # Unknown memory_ref is kept on AgentOutput so MAUR can evaluate and exclude it, with a WARN
    assert out.memory_ref == ["M99"]
    assert out.messages == []
    assert out.memory_update is None
    assert len(out.parse_errors) == 3
    assert all(e.startswith("WARN:") for e in out.parse_errors)


def test_fatal_errors_when_response_or_action_missing():
    parser = make_xml_parser()
    out1, err1 = parser("I think I will pass to A2.")
    assert out1.parse_ok is False
    assert len(err1) == 1

    out2, err2 = parser("<RESPONSE><RATIONALE>thinking</RATIONALE></RESPONSE>")
    assert out2.parse_ok is False
    assert len(err2) == 1


def test_render_message_teammate_view():
    msg = Message(
        sender="A2",
        is_captain_channel=False,
        kind="action",
        text="screen for me",
        directive=Directive(to="A3", act="SCREEN", target="B1"),
    )
    assert (
        render_message(msg)
        == "<A2>[action to=A3 act=SCREEN target=B1] screen for me [/action]</A2>"
    )
    cap_msg = Message(
        sender="A1",
        is_captain_channel=True,
        kind="tactic",
        text="run horns",
        cs="01",
    )
    assert render_message(cap_msg) == "<A1><c>[tactic cs=01] run horns [/tactic]</c></A1>"


def test_json_to_output_equivalence():
    assert RESPONSE_JSON_SCHEMA["type"] == "json_schema"
    ctx = ParseContext(
        player_id="A1",
        known_memory_ids=frozenset({"M01", "M03"}),
        known_cs_keys=frozenset({"01"}),
    )
    json_payload = {
        "action": {"type": "PASS", "target": "A2", "memory_ref": ["M01", "M03"]},
        "messages": [
            {
                "kind": "action",
                "text": "set a screen on B1 for me",
                "directive": {"to": "A3", "act": "SCREEN", "target": "B1"},
                "cs": None,
            },
            {
                "kind": "tactic",
                "text": "let's run pick and pop on the left",
                "directive": None,
                "cs": "01",
            },
            {
                "kind": "info",
                "text": "B1 keeps gambling on steals",
                "directive": None,
                "cs": None,
            },
        ],
        "captain_call": {
            "maintain": False,
            "tactic": "pick and roll on the left wing, A2 handles",
            "cs": None,
            "directives": [
                {
                    "to": "A3",
                    "act": "SCREEN",
                    "target": "A2",
                    "text": "screen for A2",
                }
            ],
        },
        "memory_update": {
            "opponent": "B1",
            "category": "defensive_tendency",
            "tendency": "leaves passing lanes open on contested drives",
        },
        "cs_update": {
            "side": "offense",
            "opponent_strategy": "B switches every screen",
            "counter_strategy": "slip the screen and cut to the rim",
        },
        "rationale": "B1 is overplaying; A2 is open on the cut.",
    }
    from_json = json_to_output(json_payload, ctx)
    from_xml = parse_response(FULL_VALID_XML, ctx)

    assert from_json.parse_ok is True
    assert from_json.action == from_xml.action
    assert from_json.target == from_xml.target
    assert from_json.memory_ref == from_xml.memory_ref
    assert from_json.messages == from_xml.messages
    assert from_json.captain_call == from_xml.captain_call
    assert from_json.memory_update == from_xml.memory_update
    assert from_json.cs_update == from_xml.cs_update
    assert from_json.rationale == from_xml.rationale
    assert "<RESPONSE>" in from_json.raw_text


# Property-based round-trip test with hypothesis
_SAFE_TEXT = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs", "Cc"),
        blacklist_characters=("[", "]"),
    ),
    min_size=1,
    max_size=40,
).map(str.strip).filter(
    lambda s: bool(s)
    and s.strip().upper() not in ("NONE", "NULL")
    and not s.lower().startswith("[action")
    and not s.lower().startswith("[tactic")
)

_ACTION_STRAT = st.sampled_from(sorted(ALL_ACTIONS))
_TARGET_STRAT = st.one_of(st.none(), st.sampled_from(["A2", "A3", "B1", "B2", "TOP", "PAINT"]))
_MEM_REF_STRAT = st.one_of(
    st.none(),
    st.lists(st.sampled_from(["M01", "M02", "M03"]), min_size=1, max_size=2, unique=True),
)
_DIRECTIVE_MSG_STRAT = st.builds(
    lambda to, act, target, text: Message(
        sender="A1",
        is_captain_channel=False,
        kind="action",
        text=text,
        directive=Directive(to=to, act=act, target=target),
    ),
    to=st.sampled_from(["A2", "A3"]),
    act=_ACTION_STRAT,
    target=_TARGET_STRAT,
    text=_SAFE_TEXT,
)
_INFO_MSG_STRAT = st.builds(
    lambda text: Message(sender="A1", is_captain_channel=False, kind="info", text=text),
    text=_SAFE_TEXT,
)
_MEM_UPDATE_STRAT = st.one_of(
    st.none(),
    st.builds(
        MemoryProposal,
        opponent=st.sampled_from(["B1", "B2", "B3"]),
        category=st.sampled_from(sorted(VALID_MEMORY_CATEGORIES)),
        tendency=_SAFE_TEXT,
    ),
)
_CS_UPDATE_STRAT = st.one_of(
    st.none(),
    st.builds(
        CSProposal,
        side=st.sampled_from(["offense", "defense"]),
        opponent_strategy=_SAFE_TEXT,
        counter_strategy=_SAFE_TEXT,
    ),
)


@given(
    action=_ACTION_STRAT,
    target=_TARGET_STRAT,
    memory_ref=_MEM_REF_STRAT,
    messages=st.lists(st.one_of(_DIRECTIVE_MSG_STRAT, _INFO_MSG_STRAT), max_size=3),
    memory_update=_MEM_UPDATE_STRAT,
    cs_update=_CS_UPDATE_STRAT,
    rationale=st.one_of(st.none(), _SAFE_TEXT),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_render_parse_round_trip_property(
    action, target, memory_ref, messages, memory_update, cs_update, rationale
):
    from bball3x3.engine.actions import NO_TARGET_ACTIONS

    if action in NO_TARGET_ACTIONS:
        target = None
    original = AgentOutput(
        action=action,
        target=target,
        memory_ref=memory_ref,
        messages=messages,
        memory_update=memory_update,
        cs_update=cs_update,
        rationale=rationale,
    )
    rendered = render_response(original)
    parsed = parse_response(rendered, ParseContext(player_id="A1"))
    assert parsed.parse_ok is True
    assert parsed.parse_errors == []
    assert parsed.action == original.action
    assert parsed.target == original.target
    assert parsed.memory_ref == original.memory_ref
    assert parsed.messages == original.messages
    assert parsed.memory_update == original.memory_update
    assert parsed.cs_update == original.cs_update
    assert parsed.rationale == original.rationale
