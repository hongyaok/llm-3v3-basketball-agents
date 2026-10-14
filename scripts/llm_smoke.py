"""Manual smoke test against the real OpenRouter API (costs a fraction of a cent).

usage: set OPENROUTER_API_KEY, then run  python scripts/llm_smoke.py
"""

import asyncio

from bball3x3.config import load_llm_config
from bball3x3.llm import OpenRouterClient

PROMPT = (
    "You are basketball player A1 holding the ball. Reply with exactly this XML and nothing "
    'else: <RESPONSE><ACTION type="PASS" target="A2"/></RESPONSE>'
)


async def main() -> None:
    cfg = load_llm_config()
    cfg.runtime.cache = {"enabled": False}
    client = OpenRouterClient(cfg)
    resp = await client.complete([{"role": "user", "content": PROMPT}], cfg.players)
    print(f"model:   {resp.model}")
    print(f"reply:   {resp.text!r}")
    print(f"tokens:  {resp.prompt_tokens} in / {resp.completion_tokens} out")
    print(f"cost:    ${resp.cost_usd:.6f}")
    print(f"latency: {resp.latency_ms:.0f} ms, attempts: {resp.attempts}")


if __name__ == "__main__":
    asyncio.run(main())
