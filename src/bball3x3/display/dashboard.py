"""Read-only local dashboard for exported experiments and recorded game states."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

ASSETS = Path(__file__).with_name("web")
METRICS = {
    "ppp": ("Points per possession", "Points scored / completed possessions", False),
    "maar": ("Message alignment", "Actions aligned with teammate messages", True),
    "ccar": ("Captain alignment", "Actions aligned with captain directives", True),
    "cssr": ("Strategy selection", "Tactic calls using a valid coordination strategy", True),
    "maur": ("Memory usage", "Decisions referencing shared memory", True),
    "grounded_maur": ("Grounded memory usage", "Memory references grounded in context", True),
    "iar": ("Invalid actions", "Invalid proposed actions / all decisions; lower is better", True),
    "coordination_conflict_rate": (
        "Coordination conflicts", "Same-zone coordination conflicts", True,
    ),
}
LABELS = {"A_full": "Full system", "B_no_comm": "No communication",
          "C_no_captain": "No captain", "D_read_only": "Read-only memory"}
FEATURES = {"comms": "Communication", "captain": "Captain",
            "memory_write": "Memory updates"}
MATCHUP_MEASURES = {
    "B_no_comm": {
        "primary": ["ppp", "maar"], "context": ["ccar"],
        "adaptation": ["ppp", "maur", "cssr"],
        "note": "Message alignment applies to the communicating condition. "
                "Captain alignment remains useful context for both conditions.",
    },
    "C_no_captain": {
        "primary": ["ppp", "ccar"], "context": [], "adaptation": ["ppp"],
        "note": "Captain alignment applies only where captain directives are enabled. "
                "Strategy selection is not evaluated for the no-captain condition.",
    },
    "D_read_only": {
        "primary": ["ppp", "maur", "cssr"], "context": [],
        "adaptation": ["maur", "cssr", "ppp"],
        "note": "The read-only condition can reference initial memory but cannot write "
                "new memory or strategies. Interpret its strategy selection with that constraint.",
    },
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _locate(root: Path, marker: str) -> Path:
    """Accept either an experiment directory or its downloaded parent folder."""
    root = root.expanduser().resolve()
    if (root / marker).is_file():
        return root
    candidates = sorted(root.glob(f"*/{marker}"))
    if len(candidates) != 1:
        raise ValueError(f"Expected one experiment containing {marker} under {root}")
    return candidates[0].parents[len(Path(marker).parts) - 1]


def _pool(rows: list[dict], metric: str) -> dict:
    statuses = Counter(row.get(f"{metric}_status", "missing") for row in rows)
    valid = [row for row in rows if row.get(f"{metric}_status") == "ok"
             and _number(row.get(f"{metric}_rate")) is not None]
    numerator = sum(_number(row.get(f"{metric}_numerator")) or 0 for row in valid)
    denominator = sum(_number(row.get(f"{metric}_denominator")) or 0 for row in valid)
    status = ("ok" if len(valid) == len(rows) else "partial") if denominator else (
        next(iter(statuses)) if len(statuses) == 1 else "unavailable"
    )
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None,
            "status": status, "status_counts": dict(statuses), "games": len(valid)}


class DashboardData:
    """Read exported rates as-is, and load a compact replay only when selected."""

    def __init__(self, results_dir: Path, runs_dir: Path) -> None:
        self.results_dir = _locate(results_dir, "export/games.csv")
        runs_dir = runs_dir.expanduser().resolve()
        self.games = _read_csv(self.results_dir / "export/games.csv")
        self.teams = _read_csv(self.results_dir / "export/teams.csv")
        self.possessions = _read_csv(self.results_dir / "export/possessions.csv")
        if not self.games:
            raise ValueError("The results export contains no games")
        ids = [row["game_id"] for row in self.games]
        if len(ids) != len(set(ids)):
            raise ValueError("Game IDs must be unique in the results export")
        experiments = {row["experiment_id"] for row in self.games}
        if len(experiments) != 1:
            raise ValueError("Select an export containing a single experiment")
        self.experiment_id = next(iter(experiments))
        self.log_paths: dict[str, Path] = {}
        for game_id in ids:
            # Exported source paths can refer to another machine. Match local file names.
            if Path(game_id).name != game_id or game_id in {".", ".."}:
                raise ValueError(f"Invalid game ID: {game_id}")
            matches = sorted(runs_dir.rglob(f"{game_id}.jsonl"))
            if len(matches) > 1:
                raise ValueError(f"Multiple logs found for {game_id}; select one run folder")
            if matches:
                self.log_paths[game_id] = matches[0]
        stats_path = self.results_dir / "stats.json"
        self.stats = json.loads(stats_path.read_text()) if stats_path.is_file() else {}
        adaptation_path = self.results_dir / "plots/adaptation.csv"
        self.adaptation = _read_csv(adaptation_path) if adaptation_path.is_file() else []
        self.by_game = {row["game_id"]: row for row in self.games}

    def overview(self) -> dict:
        conditions = sorted({row["condition"] for row in self.teams})
        if len(conditions) != 2:
            raise ValueError("A dashboard experiment must contain exactly two conditions")
        baseline = self.stats.get("baseline")
        if baseline not in conditions:
            baseline = "A_full" if "A_full" in conditions else conditions[0]
        conditions = [baseline, *(c for c in conditions if c != baseline)]
        condition_rows = {c: [r for r in self.teams if r["condition"] == c] for c in conditions}
        comparison = next((r for r in self.stats.get("results", [])
                           if r["experiment_id"] == self.experiment_id), {})
        wins: Counter = Counter()
        games = []
        draws = 0
        for row in self.games:
            scores = {t: _number(row.get(f"final_score_{t}")) for t in ("A", "B")}
            complete = row.get("game_complete", "").lower() == "true"
            winner = None
            if complete and all(v is not None for v in scores.values()):
                if scores["A"] == scores["B"]:
                    draws += 1
                else:
                    winner = row[f"team_{'A' if scores['A'] > scores['B'] else 'B'}_condition"]
                    wins[winner] += 1
            games.append({
                "id": row["game_id"], "seed": row["seed"],
                "first_possession": row["first_possession"], "score": scores,
                "conditions": {t: row[f"team_{t}_condition"] for t in ("A", "B")},
                "winner": winner, "complete": complete,
                "events": _number(row.get("transitions")), "end_reason": row.get("end_reason"),
                "validation": row.get("possession_validation"),
                "available": row["game_id"] in self.log_paths,
                "ppp": {r["condition"]: _number(r["ppp_rate"]) for r in self.teams
                        if r["game_id"] == row["game_id"] and r["ppp_status"] == "ok"},
            })
        games.sort(key=lambda row: (int(row["seed"]), row["first_possession"]))
        config = json.loads(self.games[0].get("config_snapshot_json") or "{}")
        metrics = [{"id": key, "name": label, "description": description, "percent": percent,
                    "conditions": {c: _pool(condition_rows[c], key) for c in conditions},
                    "paired": comparison.get("metrics", {}).get(key)}
                   for key, (label, description, percent) in METRICS.items()]
        condition_summaries = [{
            "id": c, "label": LABELS.get(c, c.replace("_", " ")), "wins": wins[c],
            "features": {name: (condition_rows[c][0][f"{name}_enabled"].lower() == "true"
                                if condition_rows[c][0].get(f"{name}_enabled") else None)
                         for name in FEATURES},
        } for c in conditions]
        changed = [name for name in FEATURES
                   if condition_summaries[0]["features"][name] is not None
                   and condition_summaries[1]["features"][name] is not None
                   and condition_summaries[0]["features"][name]
                   != condition_summaries[1]["features"][name]] if len(conditions) == 2 else []
        title = f"{FEATURES[changed[0]]} ablation" if len(changed) == 1 else "Team comparison"
        comparison_id = comparison.get("comparison") or (
            conditions[1] if len(conditions) > 1 else None
        )
        focus = MATCHUP_MEASURES.get(comparison_id, {
            "primary": ["ppp"], "context": [], "adaptation": ["ppp"], "note": "",
        })
        return {
            "experiment_id": self.experiment_id, "model": self.games[0]["model_slug"],
            "conditions": condition_summaries,
            "study": {"title": title, "baseline": baseline,
                      "comparison": comparison_id,
                      "changed_features": changed, "measures": focus},
            "validity": {"sir": _pool(self.games, "sir"),
                         "iar": next(metric for metric in metrics if metric["id"] == "iar")},
            "summary": {"games": len(games), "complete_games": sum(g["complete"] for g in games),
                        "seeds": len({g["seed"] for g in games}), "draws": draws,
                        "possessions": len(self.possessions),
                        "events": sum(_number(r["transitions"]) or 0 for r in self.games),
                        "invariant_violations": sum(_number(r["sir_numerator"]) or 0
                                                    for r in self.games),
                        "logged_cost_usd": sum(_number(r["total_cost_usd"]) or 0
                                               for r in self.games)},
            "games": games, "metrics": metrics,
            "adaptation": [{**r, "rate": _number(r.get("rate")),
                            "numerator": _number(r.get("numerator")),
                            "denominator": _number(r.get("denominator"))}
                           for r in self.adaptation],
            "statistics": {"baseline": self.stats.get("baseline"),
                           "bootstrap_replicates": self.stats.get("bootstrap_replicates"),
                           "analysis_seed": self.stats.get("analysis_seed"),
                           "model_note": self.stats.get("model_note"),
                           "possession_model": comparison.get("possession_model", {}),
                           "source_excluded_games": self.stats.get("source_excluded_games", [])},
            "config": config,
            "sources": {"results": self.results_dir.name,
                        "logs_matched": len(self.log_paths), "export": "export/*.csv",
                        "stats": "stats.json", "adaptation": "plots/adaptation.csv"},
        }

    @lru_cache(maxsize=4)
    def replay(self, game_id: str) -> dict:
        if game_id not in self.log_paths:
            raise KeyError("No local replay log for this game")
        events: dict[int, dict] = defaultdict(lambda: {
            "decisions": [], "messages": [], "captain_calls": [], "possessions_ended": [],
        })
        start = end = None
        path = self.log_paths[game_id]
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("record must be an object")
                except ValueError as exc:
                    raise ValueError(f"{path.name}:{line_number}: {exc}") from exc
                kind = record.get("record_type")
                if kind == "game_start":
                    start = record
                    continue
                if kind == "game_end":
                    end = record
                    continue
                event_idx = record.get("event_idx")
                if not isinstance(event_idx, int):
                    continue
                frame = events[event_idx]
                if kind == "state":
                    frame["state"] = record.get("state")
                elif kind == "decision":
                    parsed = record.get("parsed_output") or {}
                    frame["decisions"].append({
                        **{k: record.get(k) for k in ("player", "team", "executed_action",
                            "executed_target", "invalid_reason", "parse_ok", "memory_ref")},
                        "rationale": parsed.get("rationale"),
                        "proposed_action": parsed.get("action"),
                    })
                elif kind in {"message", "captain_call", "possession_end"}:
                    field = {"message": "messages", "captain_call": "captain_calls",
                             "possession_end": "possessions_ended"}[kind]
                    frame[field].append(record)
                elif kind in {"resolution", "referee"}:
                    frame[kind] = record
        if not start or start.get("game_id") != game_id or not start.get("initial_state"):
            raise ValueError(f"{path.name}: missing or mismatched game_start")
        frames = [{"event_idx": 0, "state": start["initial_state"], "decisions": [],
                   "messages": [], "captain_calls": [], "possessions_ended": []}]
        for event_idx, frame in sorted(events.items()):
            if not frame.get("state"):
                raise ValueError(f"{path.name}: missing state at event {event_idx}")
            frames.append({"event_idx": event_idx, **frame})
        exported = self.by_game[game_id]
        warnings = []
        if not end:
            warnings.append("The local log has no game_end record; replay may be incomplete.")
        elif any(end["final_score"][t] != _number(exported.get(f"final_score_{t}"))
                 for t in ("A", "B")):
            warnings.append("Local final score differs from the results export.")
        config = start.get("config_snapshot", {})
        court = config.get("simulation", config).get("court", {})
        return {"id": game_id, "seed": start["seed"],
                "conditions": start["team_conditions"], "coordination": start["coordination"],
                "first_possession": start["first_possession"], "court": court,
                "frames": frames, "end": end, "warnings": warnings,
                "possessions": [r for r in self.possessions if r["game_id"] == game_id]}


class DashboardCatalog:
    """Expose complete saved experiments from one local results directory."""

    def __init__(self, root: Path | None = None, data: DashboardData | None = None) -> None:
        self.root = root.expanduser().resolve() if root else None
        self.entries: dict[str, DashboardData] = {}
        if data:
            self.entries[data.experiment_id] = data
        if self.root:
            self.refresh()

    def refresh(self) -> None:
        if self.root is None:
            return
        if not self.root.is_dir():
            raise ValueError(f"Experiment directory does not exist: {self.root}")
        for results in sorted(self.root.glob("*_results")):
            exports = list(results.glob("*/export/games.csv")) if results.is_dir() else []
            if not exports or any(
                not (games.parent / name).is_file()
                for games in exports for name in ("teams.csv", "possessions.csv")
            ):
                continue
            runs = self.root / f"{results.name.removesuffix('_results')}_runs"
            data = DashboardData(results, runs)
            existing = self.entries.get(data.experiment_id)
            if existing and existing.results_dir != data.results_dir:
                raise ValueError(f"Duplicate experiment ID: {data.experiment_id}")
            self.entries[data.experiment_id] = data
        if not self.entries:
            raise ValueError(f"No complete experiment exports found under {self.root}")

    @property
    def default_id(self) -> str:
        return "abl_comms_v1" if "abl_comms_v1" in self.entries else sorted(self.entries)[0]

    def get(self, experiment_id: str | None) -> DashboardData:
        try:
            return self.entries[experiment_id or self.default_id]
        except KeyError as exc:
            raise KeyError(f"Unknown experiment: {experiment_id}") from exc

    def options(self) -> dict:
        experiments = []
        for experiment_id in sorted(self.entries):
            overview = self.entries[experiment_id].overview()
            experiments.append({"id": experiment_id, "title": overview["study"]["title"],
                                "conditions": [c["label"] for c in overview["conditions"]],
                                "games": overview["summary"]["games"]})
        return {"default": self.default_id, "experiments": experiments}

    def comparison_summary(self) -> dict:
        """Keep each experiment's rates and paired estimates separate."""
        rows = []
        for experiment_id in sorted(self.entries):
            data = self.entries[experiment_id]
            overview = data.overview()
            metrics = {metric["id"]: metric for metric in overview["metrics"]}
            primary = []
            for metric_id in overview["study"]["measures"]["primary"]:
                metric = metrics[metric_id]
                paired = metric["paired"]
                primary.append({
                    "id": metric_id, "name": metric["name"],
                    "percent": metric["percent"], "conditions": metric["conditions"],
                    "paired": ({"status": paired.get("status"),
                                "effect_mean": paired.get("effect_mean"),
                                "bootstrap_95_ci": paired.get("bootstrap_95_ci"),
                                "p_value": (paired.get("wilcoxon") or {}).get("p_value"),
                                "n_seeds": paired.get("n_seeds")}
                               if paired else None),
                })
            rows.append({
                "experiment_id": experiment_id, "title": overview["study"]["title"],
                "conditions": overview["conditions"], "summary": overview["summary"],
                "primary_metrics": primary, "logs_matched": len(data.log_paths),
                "validity": overview["validity"],
                "measure_note": overview["study"]["measures"]["note"],
                "has_stats": bool(data.stats), "has_adaptation": bool(data.adaptation),
            })
        return {"experiments": rows}


def make_handler(source: DashboardData | DashboardCatalog) -> type[BaseHTTPRequestHandler]:
    catalog = source if isinstance(source, DashboardCatalog) else DashboardCatalog(data=source)

    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, content: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)

        def send_json(self, value: Any, status: int = 200) -> None:
            self.send_bytes(json.dumps(value, allow_nan=False).encode(),
                            "application/json; charset=utf-8", status)

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            path = unquote(url.path)
            selected = parse_qs(url.query).get("experiment", [None])[0]
            try:
                if path == "/api/experiments":
                    catalog.refresh()
                    self.send_json(catalog.options())
                elif path == "/api/comparisons":
                    catalog.refresh()
                    self.send_json(catalog.comparison_summary())
                elif path == "/api/experiment":
                    data = catalog.get(selected)
                    self.send_json(data.overview())
                elif path.startswith("/api/games/"):
                    data = catalog.get(selected)
                    self.send_json(data.replay(path.removeprefix("/api/games/")))
                elif path in {"/downloads/games.csv", "/downloads/teams.csv",
                              "/downloads/possessions.csv"}:
                    data = catalog.get(selected)
                    self.send_bytes((data.results_dir / "export" / Path(path).name).read_bytes(),
                                    "text/csv; charset=utf-8")
                elif path == "/downloads/stats.json":
                    data = catalog.get(selected)
                    self.send_json(data.stats)
                elif path in {"/", "/index.html", "/app.js", "/style.css", "/replay.css"}:
                    name = "index.html" if path == "/" else path[1:]
                    mime = {"html": "text/html", "js": "text/javascript", "css": "text/css"}
                    self.send_bytes((ASSETS / name).read_bytes(),
                                    f"{mime[name.rsplit('.', 1)[1]]}; charset=utf-8")
                else:
                    self.send_json({"error": "Not found"}, 404)
            except KeyError as exc:
                self.send_json({"error": str(exc)}, 404)
            except (OSError, ValueError) as exc:
                self.send_json({"error": str(exc)}, 422)

    return Handler


def serve_dashboard(results_dir: Path | None = None, runs_dir: Path | None = None,
                    port: int = 8765, experiments_root: Path = Path("runs")) -> None:
    if (results_dir is None) != (runs_dir is None):
        raise ValueError("--results and --runs must be provided together")
    catalog = (DashboardCatalog(data=DashboardData(results_dir, runs_dir))
               if results_dir is not None and runs_dir is not None
               else DashboardCatalog(root=experiments_root))
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(catalog))
    print(f"Courtside · {len(catalog.entries)} experiment(s): "
          f"http://127.0.0.1:{server.server_port}", flush=True)
    print("Saved experiments and replay logs · Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
