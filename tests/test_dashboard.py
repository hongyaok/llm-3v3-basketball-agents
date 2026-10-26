"""Dashboard rates and replay evidence must agree with the saved artifacts."""

import csv
import json
from pathlib import Path

import pytest

from bball3x3.display.dashboard import DashboardData, _pool, make_handler


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def experiment(tmp_path):
    results = tmp_path / "results" / "study"
    runs = tmp_path / "runs" / "study"
    runs.mkdir(parents=True)
    write_csv(results / "export/games.csv", [{
        "experiment_id": "study", "game_id": "game-1", "seed": "101",
        "first_possession": "B", "team_A_condition": "A_full",
        "team_B_condition": "B_no_comm", "game_complete": "True",
        "final_score_A": "2", "final_score_B": "1", "transitions": "1",
        "sir_numerator": "0", "total_cost_usd": "0", "model_slug": "test-model",
        "source": "/unavailable/remote/game-1.jsonl", "config_snapshot_json": "{}",
    }])
    write_csv(results / "export/teams.csv", [{
        "game_id": "game-1", "condition": condition,
        "ppp_numerator": points, "ppp_denominator": "2", "ppp_rate": rate,
        "ppp_status": "ok", "maar_status": "ok" if team == "A" else "not_applicable",
        "comms_enabled": str(team == "A"), "captain_enabled": "True",
        "memory_write_enabled": "True",
    } for team, condition, points, rate in [("A", "A_full", "2", "1"),
                                          ("B", "B_no_comm", "1", "0.5")]])
    write_csv(results / "export/possessions.csv", [{
        "game_id": "game-1", "possession_id": "p0001", "start_event_idx": "1",
    }])
    records = [
        {"record_type": "game_start", "game_id": "game-1", "seed": 101,
         "team_conditions": {"A": "A_full", "B": "B_no_comm"},
         "coordination": {"A": {"comms": True}, "B": {"comms": False}},
         "first_possession": "B", "initial_state": {"score": {"A": 0, "B": 0}}},
        {"record_type": "decision", "event_idx": 1, "player": "B1", "team": "B",
         "parsed_output": {"action": "SHOOT", "rationale": "A recorded rationale"},
         "executed_action": "HOLD", "invalid_reason": "ILLEGAL_POSSESSION"},
        {"record_type": "message", "event_idx": 1, "sender": "A1", "team": "A",
         "text": "<script>not executable</script>", "delivered_at": 2, "suppressed": False},
        {"record_type": "resolution", "event_idx": 1, "shots": None,
         "scoring_events": [{"team": "A", "points": 2}]},
        {"record_type": "state", "event_idx": 1, "state": {"score": {"A": 2, "B": 1}}},
        {"record_type": "game_end", "final_score": {"A": 2, "B": 1}},
    ]
    path = runs / "game-1.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records))
    return results.parent, runs.parent, path


def test_pool_uses_counts_and_preserves_unavailable_status():
    rows = [
        {"ppp_numerator": "1", "ppp_denominator": "2", "ppp_rate": ".5",
         "ppp_status": "ok"},
        {"ppp_numerator": "9", "ppp_denominator": "10", "ppp_rate": ".9",
         "ppp_status": "ok"},
        {"ppp_numerator": "100", "ppp_denominator": "100", "ppp_rate": "",
         "ppp_status": "insufficient_evidence"},
    ]
    metric = _pool(rows, "ppp")
    assert metric["rate"] == pytest.approx(10 / 12)
    assert metric["rate"] != pytest.approx(.7)  # not an unweighted mean of game rates
    assert metric["status"] == "partial"
    assert metric["games"] == 2
    unavailable = _pool([{"maar_status": "not_applicable"}], "maar")
    assert unavailable["rate"] is None
    assert unavailable["status"] == "not_applicable"


def test_overview_matches_local_logs_and_condition_identity(experiment):
    results, runs, _ = experiment
    data = DashboardData(results, runs)
    overview = data.overview()
    assert overview["summary"]["games"] == 1
    assert overview["games"][0]["available"]
    assert overview["games"][0]["winner"] == "A_full"
    assert overview["conditions"][0]["wins"] == 1
    assert overview["conditions"][1]["features"]["comms"] is False
    assert "/unavailable/remote" not in json.dumps(overview)
    assert overview["metrics"][1]["conditions"]["B_no_comm"]["rate"] is None


def test_replay_keeps_initial_and_post_event_states_and_message_timing(experiment):
    results, runs, _ = experiment
    replay = DashboardData(results, runs).replay("game-1")
    assert [f["event_idx"] for f in replay["frames"]] == [0, 1]
    assert replay["frames"][0]["state"]["score"] == {"A": 0, "B": 0}
    event = replay["frames"][1]
    assert event["state"]["score"] == {"A": 2, "B": 1}
    assert event["messages"][0]["delivered_at"] == 2
    assert event["decisions"][0]["proposed_action"] == "SHOOT"
    assert event["decisions"][0]["executed_action"] == "HOLD"
    assert event["decisions"][0]["rationale"] == "A recorded rationale"
    assert event["resolution"]["shots"] is None
    assert replay["warnings"] == []


def test_replay_reports_bad_records_and_does_not_invent_missing_states(experiment):
    results, runs, path = experiment
    data = DashboardData(results, runs)
    with pytest.raises(KeyError):
        data.replay("../../outside")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    path.write_text("\n".join(json.dumps(r) for r in records if r["record_type"] != "state"))
    with pytest.raises(ValueError, match="missing state at event 1"):
        data.replay("game-1")
    path.write_text('{"invalid":')
    with pytest.raises(ValueError, match=r"game-1.jsonl:1"):
        data.replay("game-1")


def test_http_routes_only_serve_explicit_assets_and_known_games(experiment):
    results, runs, _ = experiment
    handler_type = make_handler(DashboardData(results, runs))
    handler = object.__new__(handler_type)
    received = []
    handler.send_json = lambda value, status=200: received.append((status, value))
    handler.send_bytes = lambda value, mime, status=200: received.append((status, mime))
    for route in ("/../../pyproject.toml", "/downloads/../../pyproject.toml",
                  "/api/games/%2E%2E%2Foutside"):
        handler.path = route
        handler.do_GET()
        assert received[-1][0] == 404
    handler.path = "/api/experiment"
    handler.do_GET()
    assert received[-1][0] == 200
    assert received[-1][1]["experiment_id"] == "study"
    handler.path = "/"
    handler.do_GET()
    assert received[-1] == (200, "text/html; charset=utf-8")


def test_ambiguous_results_root_is_reported(tmp_path):
    with pytest.raises(ValueError, match="Expected one experiment"):
        DashboardData(tmp_path, Path("unused"))
