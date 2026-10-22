import asyncio

from bball3x3.referee import DEFAULT_CALL_PROBS, RuleBasedReferee
from bball3x3.referee.validation import CASES, score

ALWAYS = {kind: 1.0 for kind in DEFAULT_CALL_PROBS}
NEVER = {kind: 0.0 for kind in DEFAULT_CALL_PROBS}


def _contact(cases):
    return [c for c in cases if c.state.contact_event.contact_detected]


def test_validation_set_has_30_contact_and_10_clean_states():
    assert len(_contact(CASES)) == 30
    assert len(CASES) == 40


def test_certain_calls_match_every_expected_decision():
    result = asyncio.run(score(RuleBasedReferee(seed=1, call_probs=ALWAYS)))
    assert result == {"accuracy": 1.0, "false_call_rate": 0.0}


def test_zero_rates_never_call():
    referee = RuleBasedReferee(seed=1, call_probs=NEVER)
    assert all(referee.decide(c.state).call == "NONE" for c in CASES)


def test_same_seed_gives_same_calls():
    first = RuleBasedReferee(seed=7)
    second = RuleBasedReferee(seed=7)
    for case in CASES * 5:
        assert first.decide(case.state) == second.decide(case.state)


def test_call_rate_follows_probability():
    case = next(c for c in CASES if c.name == "drive_block_A1")
    referee = RuleBasedReferee(seed=3)
    calls = sum(referee.decide(case.state).call == "FOUL" for _ in range(2000))
    assert abs(calls / 2000 - DEFAULT_CALL_PROBS["BODY_CONTACT_DRIVE"]) < 0.05

