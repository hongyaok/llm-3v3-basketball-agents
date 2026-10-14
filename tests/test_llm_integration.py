"""WS2 done-criterion: six parallel calls return parsed AgentOutputs,
with retries, cost logging and caching verified (no API key needed)."""

import asyncio
import json
import re

import httpx2

from bball3x3.config import LLMConfig
from bball3x3.llm import OpenRouterClient, complete_with_repair
from bball3x3.schemas import AgentOutput

PLAYERS = ["A1", "A2", "A3", "B1", "B2", "B3"]
ACTION_RE = re.compile(r'<ACTION type="(\w+)"(?: target="(\w+)")?\s*/>')


def toy_parse(text):
    # stand-in for the WS3 xml parser
    m = ACTION_RE.search(text)
    if not m:
        return AgentOutput(action="HOLD", raw_text=text, parse_ok=False), ["no <ACTION> tag"]
    return AgentOutput(action=m.group(1), target=m.group(2), raw_text=text), []


def test_six_parallel_player_calls(tmp_path):
    cfg = LLMConfig()
    cfg.runtime.cache = {"enabled": True, "path": str(tmp_path / "c.sqlite")}
    failed_once = set()

    async def openrouter(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        player = prompt.split()[-1]
        if player == "B2" and player not in failed_once:
            failed_once.add(player)
            return httpx2.Response(429, json={"error": {"message": "rate limited"}})
        return httpx2.Response(
            200,
            json={
                "id": "g",
                "object": "chat.completion",
                "created": 0,
                "model": cfg.players.model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": f'<RESPONSE><ACTION type="DEFEND" target="{player}"/>'
                            "</RESPONSE>",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cost": 0.001,
                },
            },
        )

    client = OpenRouterClient(
        cfg,
        api_key="test-key",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(openrouter)),
        retry_wait_s=0,
    )

    async def decide_all():
        return await asyncio.gather(
            *(
                complete_with_repair(
                    client, [{"role": "user", "content": f"you are {p}"}], cfg.players, toy_parse
                )
                for p in PLAYERS
            )
        )

    results = asyncio.run(decide_all())
    assert [r.parsed.target for r in results] == PLAYERS
    assert all(r.ok and r.parsed.parse_ok for r in results)
    assert results[PLAYERS.index("B2")].responses[0].attempts == 2
    assert client.budget.calls == 6
    assert abs(client.budget.spent_usd - 0.006) < 1e-9

    # same six prompts again: all served from cache, nothing charged
    again = asyncio.run(decide_all())
    assert all(r.responses[0].cached for r in again)
    assert client.budget.calls == 6
