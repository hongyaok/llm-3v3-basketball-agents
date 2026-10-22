import asyncio
import json

import httpx2
import openai
import pytest

from bball3x3.config import LLMConfig
from bball3x3.llm import BudgetExceededError, BudgetTracker
from bball3x3.llm.client import OpenRouterClient

MSGS = [{"role": "system", "content": "rules"}, {"role": "user", "content": "you are A1"}]


def ok_body(text="<RESPONSE/>", prompt=10, completion=5, cost=0.002):
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 0,
        "model": "openai/gpt-oss-120b",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cost": cost,
        },
    }


class FakeOpenRouter:
    """Stands in for the OpenRouter HTTP API; replies are status codes or bodies, in order."""

    def __init__(self, replies=None, delay_s=0.0):
        self.replies = list(replies or [])
        self.requests = []
        self.delay_s = delay_s
        self.in_flight = 0
        self.peak_in_flight = 0

    async def handle(self, request):
        self.requests.append(request)
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay_s)
            reply = self.replies.pop(0) if self.replies else ok_body()
            if isinstance(reply, int):
                return httpx2.Response(reply, json={"error": {"message": f"status {reply}"}})
            return httpx2.Response(200, json=reply)
        finally:
            self.in_flight -= 1

    def body(self, i=0):
        return json.loads(self.requests[i].content)


def make_client(server, cfg=None, **kwargs):
    cfg = cfg or LLMConfig()
    kwargs.setdefault("retry_wait_s", 0)
    return OpenRouterClient(
        cfg,
        api_key="test-key",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(server.handle)),
        **kwargs,
    )


def run(coro):
    return asyncio.run(coro)


def test_complete_sends_openrouter_request_and_returns_usage():
    cfg = LLMConfig()
    cfg.provider.routing = {"order": ["OpenAI"], "allow_fallbacks": False}
    server = FakeOpenRouter([ok_body(text="<RESPONSE>hi</RESPONSE>", prompt=12, completion=3)])
    client = make_client(server, cfg)

    resp = run(client.complete(MSGS, cfg.players))

    req = server.requests[0]
    assert str(req.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer test-key"
    assert req.headers["x-title"] == "dsa4213-3x3-agents"
    body = server.body()
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["messages"] == MSGS
    assert body["temperature"] == 0.7
    assert body["top_p"] == 1.0
    assert body["max_tokens"] == 500
    assert body["provider"] == {"order": ["OpenAI"], "allow_fallbacks": False}
    assert "seed" not in body
    assert "response_format" not in body

    assert resp.text == "<RESPONSE>hi</RESPONSE>"
    assert resp.prompt_tokens == 12
    assert resp.completion_tokens == 3
    assert resp.cost_usd == pytest.approx(0.002)
    assert resp.cached is False
    assert resp.attempts == 1


def test_seed_is_sent_when_configured():
    cfg = LLMConfig()
    cfg.players.seed = 42
    server = FakeOpenRouter()
    run(make_client(server, cfg).complete(MSGS, cfg.players))
    assert server.body()["seed"] == 42


def test_json_output_format_sends_response_format():
    cfg = LLMConfig()
    cfg.players.output_format = "json"
    schema = {"type": "json_schema", "json_schema": {"name": "agent_output", "schema": {}}}
    server = FakeOpenRouter()
    run(make_client(server, cfg).complete(MSGS, cfg.players, response_format=schema))
    assert server.body()["response_format"] == schema


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retries_transient_errors_then_succeeds(status):
    server = FakeOpenRouter([status, ok_body(text="recovered")])
    resp = run(make_client(server).complete(MSGS, LLMConfig().players))
    assert resp.text == "recovered"
    assert resp.attempts == 2
    assert len(server.requests) == 2


def test_does_not_retry_bad_request():
    server = FakeOpenRouter([400])
    with pytest.raises(openai.BadRequestError):
        run(make_client(server).complete(MSGS, LLMConfig().players))
    assert len(server.requests) == 1


def test_gives_up_after_max_retries():
    cfg = LLMConfig()
    cfg.players.max_retries = 2
    server = FakeOpenRouter([429, 429, 429, 429])
    with pytest.raises(openai.RateLimitError):
        run(make_client(server, cfg).complete(MSGS, cfg.players))
    assert len(server.requests) == 3  # first try + 2 retries


def test_concurrency_is_capped_by_semaphore():
    cfg = LLMConfig()
    cfg.runtime.max_concurrent_requests = 2
    server = FakeOpenRouter(delay_s=0.05)
    client = make_client(server, cfg)

    async def six_calls():
        return await asyncio.gather(
            *(
                client.complete([{"role": "user", "content": f"A{i}"}], cfg.players)
                for i in range(6)
            )
        )

    results = run(six_calls())
    assert len(results) == 6
    assert server.peak_in_flight == 2


def test_cache_hit_skips_api_and_budget(tmp_path):
    cfg = LLMConfig()
    cfg.runtime.cache = {"enabled": True, "path": str(tmp_path / "c.sqlite")}
    server = FakeOpenRouter([ok_body(text="first", cost=0.01)])
    budget = BudgetTracker(max_usd=1.0)
    client = make_client(server, cfg, budget=budget)

    first = run(client.complete(MSGS, cfg.players))
    second = run(client.complete(MSGS, cfg.players))

    assert len(server.requests) == 1
    assert first.cached is False
    assert second.cached is True
    assert second.text == "first"
    assert budget.calls == 1
    assert budget.spent_usd == pytest.approx(0.01)


def test_cache_disabled_always_calls_api(tmp_path):
    cfg = LLMConfig()
    cfg.runtime.cache = {"enabled": False, "path": str(tmp_path / "c.sqlite")}
    server = FakeOpenRouter()
    client = make_client(server, cfg)
    run(client.complete(MSGS, cfg.players))
    run(client.complete(MSGS, cfg.players))
    assert len(server.requests) == 2


def test_budget_charged_and_hard_stop():
    server = FakeOpenRouter([ok_body(cost=0.6), ok_body(cost=0.6)])
    budget = BudgetTracker(max_usd=0.5)
    client = make_client(server, budget=budget)

    run(client.complete(MSGS, LLMConfig().players))
    assert budget.spent_usd == pytest.approx(0.6)
    with pytest.raises(BudgetExceededError):
        run(client.complete(MSGS, LLMConfig().players))
    assert len(server.requests) == 1


def test_budget_defaults_to_runtime_config():
    cfg = LLMConfig()
    cfg.runtime.budget = {"max_usd_per_experiment": 7.5}
    client = make_client(FakeOpenRouter(), cfg)
    assert client.budget.max_usd == 7.5


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterClient(LLMConfig())


def test_api_key_read_from_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    server = FakeOpenRouter()
    client = OpenRouterClient(
        LLMConfig(),
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(server.handle)),
    )
    run(client.complete(MSGS, LLMConfig().players))
    assert server.requests[0].headers["authorization"] == "Bearer env-key"


def test_referee_params_work_without_player_only_fields():
    cfg = LLMConfig()
    server = FakeOpenRouter()
    run(make_client(server, cfg).complete(MSGS, cfg.referee))
    body = server.body()
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 200


def test_reasoning_and_finish_reason():
    from bball3x3.llm import QuotaExceededError, RateLimiter

    _ = (QuotaExceededError, RateLimiter)
    cfg = LLMConfig()
    cfg.players.reasoning = {"effort": "low"}
    body_payload = ok_body(text="<RESPONSE/>")
    body_payload["choices"][0]["finish_reason"] = "length"
    server = FakeOpenRouter([body_payload])
    resp = run(make_client(server, cfg).complete(MSGS, cfg.players))
    assert server.body()["reasoning"] == {"effort": "low"}
    assert resp.finish_reason == "length"


def test_daily_quota_429_aborts_without_retrying():
    from bball3x3.llm import QuotaExceededError

    class QuotaServer(FakeOpenRouter):
        async def handle(self, request):
            self.requests.append(request)
            return httpx2.Response(
                429,
                json={"error": {"message": "Rate limit exceeded: free-models-per-day."}},
            )

    cfg = LLMConfig()
    cfg.players.max_retries = 3
    server = QuotaServer()
    with pytest.raises(QuotaExceededError, match="free-models-per-day"):
        run(make_client(server, cfg).complete(MSGS, cfg.players))
    assert len(server.requests) == 1


def test_rpm_rate_limiter_paces_bursts():
    from bball3x3.llm import RateLimiter

    fake_now = 0.0
    slept: list[float] = []

    def clock() -> float:
        return fake_now

    async def sleep(dt: float) -> None:
        nonlocal fake_now
        slept.append(dt)
        fake_now += dt

    limiter = RateLimiter(3, window_s=60.0, clock=clock, sleep=sleep)
    cfg = LLMConfig()
    server = FakeOpenRouter()
    client = make_client(server, cfg, rate_limiter=limiter)

    async def five_calls():
        for i in range(5):
            await client.complete([{"role": "user", "content": f"req-{i}"}], cfg.players)

    run(five_calls())
    assert len(server.requests) == 5
    # First 3 calls need no sleep; 4th waits 60s; 5th is at t=60s where 2nd/3rd also expired
    assert slept == [pytest.approx(60.0)]
