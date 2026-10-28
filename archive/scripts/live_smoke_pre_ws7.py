"""PRE_WS7 live smoke: tiny LLM game with in-memory LLM-referee override."""
from __future__ import annotations
import asyncio, datetime, json, os, pathlib

def _load_env() -> None:
    envp = pathlib.Path(".env")
    if envp.exists():
        for line in envp.read_text(encoding="utf-8").splitlines():
            line=line.strip()
            if line and not line.startswith("#") and "=" in line:
                k,v=line.split("=",1)
                k=k.strip(); v=v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k]=v

async def main() -> None:
    _load_env()
    print("KEY:", "PRESENT" if os.environ.get("OPENROUTER_API_KEY") else "ABSENT", flush=True)
    from bball3x3.analysis.log_reader import read_game_log
    from bball3x3.config import load_llm_config
    from bball3x3.llm.client import OpenRouterClient
    from bball3x3.runner.llm_game import run_llm_game
    cfg=load_llm_config()
    print(f"FILE players: {cfg.players.model} referee: {cfg.referee.model} {cfg.referee.enabled} {cfg.referee.backend}", flush=True)
    cfg_live=cfg.model_copy(update={
        "players": cfg.players.model_copy(update={"model": "minimax/minimax-m3.1-flash"}),
        "referee": cfg.referee.model_copy(update={"enabled": True, "backend": "llm"}),
    })
    print(f"LIVE players: {cfg_live.players.model} referee: {cfg_live.referee.enabled} {cfg_live.referee.backend} {cfg_live.referee.model}", flush=True)
    ts=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir=pathlib.Path(f"runs/pre_ws7/{ts}_seed_101")
    outdir.mkdir(parents=True, exist_ok=True)
    out=outdir/"smoke.jsonl"
    pb=OpenRouterClient(cfg_live)
    try:
        res=await run_llm_game(llm=pb, path=str(out), seed=101, llm_config=cfg_live, max_events=5, experiment_id="pre_ws7", game_id="pre_ws7_s101_smoke", replicate_id="seed_101")
    finally:
        try: await pb.aclose()
        except Exception: pass
    print(f"SMOKE events={res['events']} score={res['score']} complete={res['game_complete']} end={res['end_reason']} iar={round(res['iar'],4)} parse_fail={round(res['parse_failure_rate'],4)}", flush=True)
    game=read_game_log(str(out))
    refs=game.by_type.get("referee",[])
    print(f"REFEREE_RECORDS={len(refs)}", flush=True)
    if refs:
        r0=refs[0]
        print(f"REF0 model={r0.model} chunks={len(r0.retrieved_chunk_ids or [])} query_len={len(r0.query or '')} call={r0.decision.call}", flush=True)
        print(f"REFS_WITH_CHUNKS={sum(1 for r in refs if r.retrieved_chunk_ids)}/{len(refs)}", flush=True)
    (outdir/"smoke_summary.json").write_text(json.dumps({"events":res["events"],"score":res["score"],"complete":res["game_complete"],"refs":len(refs),"player_model":cfg_live.players.model,"ref_model":cfg_live.referee.model},indent=2))
    print(f"OUT={out}", flush=True)
    print("SMOKE_VERDICT: PASS" if res["events"]==5 else "SMOKE_VERDICT: CHECK", flush=True)

if __name__=="__main__":
    asyncio.run(main())
