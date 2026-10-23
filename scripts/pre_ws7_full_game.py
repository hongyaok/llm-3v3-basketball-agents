"""PRE_WS7 full game: live LLM players + live LLM referee to termination.

In-memory overrides only (configs/llm.yaml is never written):
  * players.model: retired ``:free`` slug -> paid slug
  * referee.enabled / referee.backend: False/rule_based -> True/llm

Writes game.jsonl, then runs the offline (no-LLM) validation bundle:
metrics.json, possessions.json, referee_audit.json, run_manifest.json.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import pathlib
import subprocess


def _load_env() -> None:
    envp = pathlib.Path(".env")
    if not envp.exists():
        return
    for line in envp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _configs_diff_clean() -> bool:
    try:
        out = subprocess.run(
            ["git", "diff", "--", "configs/"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.stdout.strip() == ""


async def run(seed: int, max_events: int, player_model: str) -> pathlib.Path:
    _load_env()
    from bball3x3.config import load_llm_config
    from bball3x3.llm.client import OpenRouterClient
    from bball3x3.runner.llm_game import run_llm_game

    cfg = load_llm_config()
    print(
        f"FILE players={cfg.players.model} referee={cfg.referee.model} "
        f"{cfg.referee.enabled}/{cfg.referee.backend}",
        flush=True,
    )
    cfg_live = cfg.model_copy(
        update={
            "players": cfg.players.model_copy(update={"model": player_model}),
            "referee": cfg.referee.model_copy(
                update={"enabled": True, "backend": "llm"}
            ),
        }
    )
    budget = cfg_live.runtime.budget.get("max_usd_per_experiment")
    print(
        f"LIVE players={cfg_live.players.model} referee={cfg_live.referee.enabled}/"
        f"{cfg_live.referee.backend} model={cfg_live.referee.model} "
        f"budget=${budget}",
        flush=True,
    )

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = pathlib.Path(f"runs/pre_ws7/{stamp}_seed_{seed}")
    outdir.mkdir(parents=True, exist_ok=True)
    log_path = outdir / "game.jsonl"

    backend = OpenRouterClient(cfg_live)
    try:
        result = await run_llm_game(
            llm=backend,
            path=log_path,
            seed=seed,
            llm_config=cfg_live,
            max_events=max_events,
            experiment_id="pre_ws7",
            game_id=f"pre_ws7_full_s{seed}",
            replicate_id=f"seed_{seed}",
            checkpoint_path=outdir / "game.ckpt.json",
        )
    finally:
        try:
            await backend.aclose()
        except Exception:
            pass

    print(
        "FULL_GAME "
        f"events={result['events']} score={result['score']} "
        f"complete={result['game_complete']} end={result['end_reason']} "
        f"iar={round(result['iar'], 4)} "
        f"parse_fail={round(result['parse_failure_rate'], 4)} "
        f"cost=${round(result['total_cost_usd'], 4)}",
        flush=True,
    )
    return outdir


def validate(outdir: pathlib.Path, seed: int) -> dict:
    """Offline gate: strict reader, possession closure, metrics, referee audit."""
    from bball3x3.analysis.log_reader import read_game_log
    from bball3x3.analysis.metrics import compute_game_metrics
    from bball3x3.analysis.possessions import validate_possessions

    game = read_game_log(str(outdir / "game.jsonl"))
    poss = validate_possessions(game)
    metrics = compute_game_metrics(game)

    def _dump(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return obj

    (outdir / "metrics.json").write_text(
        json.dumps(_dump(metrics), indent=2, default=str), encoding="utf-8"
    )
    (outdir / "possessions.json").write_text(
        json.dumps(_dump(poss), indent=2, default=str), encoding="utf-8"
    )

    refs = game.by_type.get("referee", [])
    events = game.by_type.get("resolution", [])
    audit = [
        {
            "event_idx": r.event_idx,
            "query": r.query,
            "chunks": list(r.retrieved_chunk_ids or []),
            "call": r.decision.call,
            "offender": r.decision.offender,
            "foul_type": r.decision.foul_type,
            "violation_type": r.decision.violation_type,
            "cited": list(r.decision.rule_ids_cited or []),
            "failure_code": r.failure_code,
            "rejection_reason": r.rejection_reason,
            "model": r.model,
            "tokens": [r.prompt_tokens, r.completion_tokens],
            "latency_ms": r.latency_ms,
            "cost_usd": r.cost_usd,
        }
        for r in refs
    ]
    (outdir / "referee_audit.json").write_text(
        json.dumps(
            {
                "n_events": len(events),
                "n_referee_records": len(audit),
                "one_per_event": len(audit) == len(events),
                "with_chunks": sum(1 for a in audit if a["chunks"]),
                "parse_failures": sum(1 for a in audit if a["failure_code"]),
                "non_none_calls": sum(1 for a in audit if a["call"] != "NONE"),
                "calls_missing_citations": sum(
                    1 for a in audit if a["call"] != "NONE" and not a["cited"]
                ),
                "records": audit,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    ends = game.by_type.get("game_end", [])
    end = ends[-1] if ends else None
    manifest = {
        "run": outdir.name,
        "seed": seed,
        "events": len(events),
        "referee_records": len(audit),
        "score": dict(end.final_score) if end else None,
        "end_reason": end.end_reason if end else None,
        "ot": bool(end.ot_flag) if end else None,
        "total_cost_usd": end.total_cost_usd if end else None,
        "invariant_violations": len(game.by_type.get("invariant_violation", [])),
        "configs_clean": _configs_diff_clean(),
        "live": True,
        "note": "in-memory referee/model override only; configs/llm.yaml untouched",
    }
    (outdir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print("MANIFEST " + json.dumps(manifest), flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--max-events", type=int, default=2000)
    parser.add_argument("--player-model", default="minimax/minimax-m3.1-flash")
    parser.add_argument("--validate-only", default=None)
    args = parser.parse_args()

    if args.validate_only:
        outdir = pathlib.Path(args.validate_only)
        manifest = validate(outdir, args.seed)
        ok = (
            manifest["end_reason"] in {"WIN_SCORE", "CLOCK_EXPIRED", "OT_WIN"}
            and manifest["referee_records"] == manifest["events"] > 0
            and manifest["invariant_violations"] == 0
            and manifest["configs_clean"]
        )
        print("PRE_WS7 GATE:", "PASS" if ok else "FAIL", flush=True)
        return

    outdir = asyncio.run(run(args.seed, args.max_events, args.player_model))
    manifest = validate(outdir, args.seed)
    ok = (
        manifest["end_reason"] in {"WIN_SCORE", "CLOCK_EXPIRED", "OT_WIN"}
        and manifest["referee_records"] == manifest["events"] > 0
        and manifest["invariant_violations"] == 0
        and manifest["configs_clean"]
    )
    print("PRE_WS7 GATE:", "PASS" if ok else "FAIL", flush=True)
    print("OUTDIR:", outdir, flush=True)


if __name__ == "__main__":
    main()
