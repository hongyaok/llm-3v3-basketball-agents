"""Validation command reports labelled decisions and local game invariants."""

import json

from bball3x3.referee.validation import (
    DEFAULT_CASES,
    evaluate_cases,
    load_cases,
    main,
    run_fuzz_games,
)


def test_labelled_phase_a_suite_has_planned_size_and_reports_accuracy():
    cases = load_cases(DEFAULT_CASES)
    report = evaluate_cases(cases)

    assert (report["cases"], report["contact_cases"], report["no_contact_cases"]) == (
        40, 30, 10,
    )
    assert report["accuracy"] == {"correct": 40, "total": 40, "rate": 1.0}
    assert report["no_contact_false_call_rate"] == {
        "false_calls": 0, "total": 10, "rate": 0.0,
    }
    assert set(report["by_contact_type"]) == {
        "BODY_CONTACT_DRIVE", "REACH", "SCREEN_CONTACT", "LOOSE_BALL", "NO_CONTACT",
    }
    assert {case["expected"]["foul_type"] for case in cases
            if case["expected"]["call"] == "FOUL"} == {
        "DEFENSIVE_FOUL", "OFFENSIVE_FOUL", "SHOOTING_FOUL",
        "LOOSE_BALL_FOUL", "UNSPORTSMANLIKE", "TECHNICAL",
    }
    assert {case["expected"]["violation_type"] for case in cases
            if case["expected"]["call"] == "VIOLATION"} == {
        "GOALTENDING", "BASKET_INTERFERENCE", "STALLING",
    }
    assert all(case["expected"]["call"] == "NONE" for case in cases
               if "contact_type" not in case)


def test_validation_exits_nonzero_and_names_a_mislabelled_case(tmp_path, capsys):
    case = load_cases(DEFAULT_CASES)[0].copy()
    case["expected"] = {"call": "NONE"}
    path = tmp_path / "incorrect.jsonl"
    path.write_text(json.dumps(case) + "\n", encoding="utf-8")

    assert main(["--cases", str(path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["accuracy"]["correct"] == 0
    assert report["mismatches"][0]["id"] == case["id"]


def test_small_optional_fuzz_run_is_local_and_clean():
    report = run_fuzz_games(2)
    assert report["games"] == 2
    assert report["events"] > 0
    assert report["invariant_violations"] == 0
    assert report["truncated_games"] == 0
