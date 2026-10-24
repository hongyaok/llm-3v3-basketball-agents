"""Short live games per candidate model, with a hard spend cap across all runs.

usage: python scripts/model_selection.py --model openai/gpt-4.1-nano --events 5 --reasoning off
"""

import argparse
import asyncio
import csv
import datetime
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

OUT = Path("runs/model_selection")
LEDGER = OUT / "budget.json"
RESULTS = OUT / "results.csv"
HASH_INDEX = OUT / "hash_index"
REASONING = {"off": {"enabled": False}, "low": {"effort": "low"}, "default": None}


def load_env() -> None:
    env = Path(".env")
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


# authoritative spend straight from openrouter, independent of our own tracking
def key_usage() -> float:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return float(json.load(resp)["data"]["usage"])


def spent_so_far(cap: float) -> float:
    usage = key_usage()
    if not LEDGER.exists():
        LEDGER.write_text(json.dumps({"baseline_usage": usage, "cap_usd": cap}))
    baseline = json.loads(LEDGER.read_text())["baseline_usage"]
    return usage - baseline


# the referee searches a hash-embedded copy of the same rule chunks,
# so no sentence-transformers model is needed (data/rules stays untouched)
def hash_index() -> Path:
    import hashlib

    import numpy as np

    from bball3x3.referee.index import embed_chunks

    if (HASH_INDEX / "index_manifest.json").exists():
        return HASH_INDEX
    HASH_INDEX.mkdir(parents=True)
    source = Path("data/rules")
    chunks = (source / "chunks.jsonl").read_bytes()
    (HASH_INDEX / "chunks.jsonl").write_bytes(chunks)
    texts = [json.loads(line)["text"] for line in chunks.decode("utf-8").splitlines()]
    vectors, model = embed_chunks(texts, "hash")
    np.save(HASH_INDEX / "embeddings.npy", vectors)
    manifest = json.loads((source / "index_manifest.json").read_text(encoding="utf-8"))
    manifest.update({
        "embedding_backend": "hash",
        "embedding_model": model,
        "embedding_shape": list(vectors.shape),
        "embeddings_sha256": hashlib.sha256(
            (HASH_INDEX / "embeddings.npy").read_bytes()
        ).hexdigest(),
    })
    (HASH_INDEX / "index_manifest.json").write_text(json.dumps(manifest, indent=2))
    return HASH_INDEX


def summarise(path: Path) -> dict:
    from bball3x3.analysis import read_game_log

    game = read_game_log(path)
    decs = game.by_type.get("decision", [])
    refs = game.by_type.get("referee", [])
    n = max(len(decs), 1)
    p_out = [(d.tokens or {}).get("completion", 0) for d in decs]
    lat = [(d.latency_ms or 0) / 1000 for d in decs]
    return {
        "events": len(game.by_type.get("resolution", [])),
        "decisions": len(decs),
        "player_parse_fail_pct": round(100 * sum(not d.parse_ok for d in decs) / n, 1),
        "iar_pct": round(100 * sum(d.invalid_reason is not None for d in decs) / n, 1),
        "ref_calls": len(refs),
        "ref_parse_fail": sum(r.failure_code is not None for r in refs),
        "ref_rejected": sum(r.rejection_reason is not None for r in refs),
        "sir_violations": len(game.by_type.get("invariant_violation", [])),
        "player_in_tokens": sum((d.tokens or {}).get("prompt", 0) for d in decs),
        "player_out_tokens": sum(p_out),
        "avg_out_per_player_call": round(sum(p_out) / n),
        "ref_in_tokens": sum(r.prompt_tokens or 0 for r in refs),
        "ref_out_tokens": sum(r.completion_tokens or 0 for r in refs),
        "avg_player_latency_s": round(sum(lat) / n, 1),
        "max_player_latency_s": round(max(lat, default=0), 1),
    }


async def run(model: str, events: int, reasoning: str, cap: float, seed: int) -> None:
    from bball3x3.config import load_llm_config
    from bball3x3.llm.budget import BudgetExceededError, BudgetTracker
    from bball3x3.llm.client import OpenRouterClient
    from bball3x3.referee import RuleRetriever
    from bball3x3.runner.llm_game import run_llm_game

    OUT.mkdir(parents=True, exist_ok=True)
    spent = spent_so_far(cap)
    if spent >= cap:
        sys.exit(f"stop: ${spent:.4f} already spent of ${cap:.2f} cap")

    cfg = load_llm_config()
    mode = REASONING[reasoning]
    cfg = cfg.model_copy(update={
        "players": cfg.players.model_copy(
            update={"model": model, "reasoning": mode, "max_tokens": 1500}
        ),
        # referee config has no reasoning field, so it is set in memory only
        "referee": cfg.referee.model_copy(
            update={"enabled": True, "backend": "llm", "model": model, "reasoning": mode}
        ),
        "runtime": cfg.runtime.model_copy(update={"cache": {"enabled": False}}),
    })

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT / f"{stamp}_{model.replace('/', '_')}_{reasoning}_{events}ev"
    run_dir.mkdir()
    path = run_dir / "game.jsonl"
    tracker = BudgetTracker(max_usd=cap - spent)
    client = OpenRouterClient(cfg, budget=tracker)
    # the referee runs on its own loop thread, so it needs its own client on the same budget
    ref_client = OpenRouterClient(cfg, budget=tracker)
    print(f"run {model} reasoning={reasoning} events={events} remaining=${cap - spent:.4f}")

    start = time.perf_counter()
    stopped = ""
    try:
        await run_llm_game(
            llm=client, path=path, seed=seed, llm_config=cfg, max_events=events,
            experiment_id="model_selection", game_id=run_dir.name, replicate_id=f"seed_{seed}",
            llm_backend_for_referee=ref_client, rule_retriever=RuleRetriever(hash_index()),
        )
    except BudgetExceededError as exc:
        stopped = f"budget: {exc}"
    finally:
        await client.aclose()
    wall = time.perf_counter() - start

    row = {
        "run": run_dir.name, "model": model, "reasoning": reasoning, "seed": seed,
        "referee_index": "hash",
    }
    row.update(summarise(path) if path.exists() else {})
    row["cost_tracked_usd"] = round(tracker.spent_usd, 5)
    row["cost_key_usd"] = round(spent_so_far(cap) - spent, 5)
    row["sec_per_event"] = round(wall / max(row.get("events", 0), 1), 1)
    row["total_spent_usd"] = round(spent_so_far(cap), 5)
    row["stopped"] = stopped
    (run_dir / "summary.json").write_text(json.dumps(row, indent=2))

    new = not RESULTS.exists()
    with RESULTS.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if new:
            writer.writeheader()
        writer.writerow(row)
    print(json.dumps(row, indent=2))
    if stopped:
        sys.exit(stopped)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--events", type=int, default=5)
    parser.add_argument("--reasoning", choices=list(REASONING), default="off")
    parser.add_argument("--cap", type=float, default=0.9)
    parser.add_argument("--seed", type=int, default=101)
    args = parser.parse_args()
    load_env()
    asyncio.run(run(args.model, args.events, args.reasoning, args.cap, args.seed))


if __name__ == "__main__":
    main()
