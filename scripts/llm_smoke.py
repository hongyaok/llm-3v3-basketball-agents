"""Manual smoke test against the real OpenRouter API (or --fake for offline validation).

usage:
  set OPENROUTER_API_KEY, then run: uv run python scripts/llm_smoke.py
  offline fake test:                uv run python scripts/llm_smoke.py --fake
"""

import argparse
import asyncio
import sys
from pathlib import Path

# ensure src/ is importable when running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bball3x3.agents.adapter import legalize_decision
from bball3x3.agents.llm_player import LLMPlayer
from bball3x3.agents.observation import build_observation
from bball3x3.config import load_llm_config, load_roster_config, load_simulation_config
from bball3x3.engine.rng import GameRNG
from bball3x3.engine.state import create_initial_state
from bball3x3.llm import FakeLLM, LegalXMLPolicy, OpenRouterClient

PROMPT = (
    "You are basketball player A1 holding the ball. Reply with exactly this XML and nothing "
    'else: <RESPONSE><ACTION type="PASS" target="A2"/></RESPONSE>'
)


async def main(use_fake: bool = False) -> None:
    cfg = load_llm_config()
    cfg.runtime.cache = {"enabled": False}
    client = FakeLLM(LegalXMLPolicy()) if use_fake else OpenRouterClient(cfg)

    resp = await client.complete([{"role": "user", "content": PROMPT}], cfg.players)
    print("=== Raw completion ===")
    print(f"model:   {resp.model}")
    print(f"reply:   {resp.text!r}")
    print(f"tokens:  {resp.prompt_tokens} in / {resp.completion_tokens} out")
    print(f"cost:    ${resp.cost_usd:.6f}")
    print(f"latency: {resp.latency_ms:.0f} ms, attempts: {resp.attempts}")

    sim_cfg = load_simulation_config()
    roster_cfg = load_roster_config()
    state = create_initial_state(sim_cfg, GameRNG.from_seed(101), first_possession="A")
    obs = build_observation(state, "A1", is_captain=True)
    profile = next((p for p in roster_cfg.players if p.slot.upper() == "P1"), None)
    player = LLMPlayer("A1", client, cfg.players, profile=profile, is_captain=True)

    res = await player.decide(obs)
    fixed, remap = legalize_decision(state, "A1", res)
    print("\n=== LLMPlayer.decide(obs) ===")
    print(f"parse_ok:        {res.kept.parse_ok} (repaired={res.repaired})")
    print(f"proposed:        {res.kept.action} target={res.kept.target}")
    remap_str = remap.reason if remap else None
    print(f"executed:        {fixed.action} target={fixed.target} (remap={remap_str})")
    print(f"tokens:          {res.prompt_tokens} in / {res.completion_tokens} out")
    print(f"finish_reason:   {res.responses[-1].finish_reason if res.responses else None}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="Use FakeLLM instead of live API")
    args = parser.parse_args()
    asyncio.run(main(use_fake=args.fake))
