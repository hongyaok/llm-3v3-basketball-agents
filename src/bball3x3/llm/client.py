import asyncio
import os
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import openai
from openai import AsyncOpenAI
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import LLMConfig
from .base import CallParams, LLMResponse, Messages
from .budget import BudgetTracker
from .cache import LLMCache, request_key

# 429, 5xx, timeouts and dropped connections are worth retrying; 4xx are not
TRANSIENT_ERRORS = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APITimeoutError,
    openai.APIConnectionError,
)

# defaults for fields only the players block defines (the referee block omits them)
DEFAULT_TIMEOUT_S = 45.0
DEFAULT_MAX_RETRIES = 3

_DAILY_QUOTA_MARKERS = (
    "per-day",
    "per day",
    "daily",
    "rpd",
    "quota",
    "free-models-per-day",
    "insufficient_quota",
    "credit",
)


class QuotaExceededError(RuntimeError):
    """Raised when a 429 indicates daily quota exhaustion rather than transient rate limiting."""


def _is_daily_quota_error(exc: BaseException) -> bool:
    if not isinstance(exc, openai.RateLimitError):
        return False
    text = str(exc).lower()
    body = getattr(exc, "body", None)
    if body is not None:
        text = f"{text} {body}".lower()
    return any(marker in text for marker in _DAILY_QUOTA_MARKERS)


class RateLimiter:
    """Client-side RPM limiter ensuring at most max_requests_per_minute in any 60s window."""

    def __init__(
        self,
        max_requests_per_minute: int,
        *,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ):
        if max_requests_per_minute <= 0:
            raise ValueError("max_requests_per_minute must be positive")
        self.max_requests = max_requests_per_minute
        self.window_s = window_s
        self._clock = clock
        self._sleep = sleep
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            while self._timestamps and now - self._timestamps[0] >= self.window_s:
                self._timestamps.popleft()
            if len(self._timestamps) < self.max_requests:
                self._timestamps.append(now)
                return
            oldest = self._timestamps.popleft()
            wait_s = max(0.0, (oldest + self.window_s) - now)
            if wait_s > 0:
                await self._sleep(wait_s)
            self._timestamps.append(max(self._clock(), oldest + self.window_s))


# async openrouter client: concurrency cap, retries, cache and budget
class OpenRouterClient:
    def __init__(
        self,
        cfg: LLMConfig,
        *,
        api_key: str | None = None,
        http_client: Any = None,
        budget: BudgetTracker | None = None,
        retry_wait_s: float = 1.0,
        rate_limiter: RateLimiter | None = None,
    ):
        self.cfg = cfg
        api_key = api_key or os.environ.get(cfg.provider.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"no OpenRouter API key: set the {cfg.provider.api_key_env} environment variable"
            )
        self._sdk = AsyncOpenAI(
            api_key=api_key,
            base_url=cfg.provider.base_url,
            max_retries=0,  # tenacity owns retries
            default_headers={"X-Title": cfg.provider.app_name},
            http_client=http_client,
        )
        self._semaphore = asyncio.Semaphore(cfg.runtime.max_concurrent_requests)
        self.retry_wait_s = retry_wait_s
        rpm = cfg.runtime.max_requests_per_minute
        self.rate_limiter = rate_limiter or (RateLimiter(rpm) if rpm is not None else None)

        cache_cfg = cfg.runtime.cache
        self.cache = LLMCache(cache_cfg["path"]) if cache_cfg.get("enabled") else None
        self.budget = budget or BudgetTracker(cfg.runtime.budget.get("max_usd_per_experiment"))

    def _build_request(
        self, messages: Messages, params: CallParams, response_format: dict[str, Any] | None
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": params.model,
            "messages": messages,
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
        }
        if getattr(params, "top_p", None) is not None:
            request["top_p"] = params.top_p
        if getattr(params, "seed", None) is not None:
            request["seed"] = params.seed
        if response_format is not None:
            request["response_format"] = response_format
        return request

    async def complete(
        self,
        messages: Messages,
        params: CallParams,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        request = self._build_request(messages, params, response_format)
        reasoning = getattr(params, "reasoning", None)
        cache_payload = {**request, "reasoning": reasoning} if reasoning is not None else request
        key = request_key(cache_payload)
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return LLMResponse(**{**hit, "cached": True, "latency_ms": 0.0})

        self.budget.check()
        max_retries = getattr(params, "max_retries", DEFAULT_MAX_RETRIES)
        timeout_s = getattr(params, "timeout_s", DEFAULT_TIMEOUT_S)
        extra_body: dict[str, Any] = {"usage": {"include": True}}
        if self.cfg.provider.routing:
            extra_body["provider"] = self.cfg.provider.routing
        if reasoning is not None:
            extra_body["reasoning"] = reasoning

        start = time.perf_counter()
        retryer = AsyncRetrying(
            retry=retry_if_exception_type(TRANSIENT_ERRORS),
            stop=stop_after_attempt(max_retries + 1),
            wait=wait_exponential(multiplier=self.retry_wait_s, max=30),
            reraise=True,
        )
        async for attempt in retryer:
            with attempt:
                if self.rate_limiter is not None:
                    await self.rate_limiter.acquire()
                # hold a slot only while a request is in flight, not during backoff
                async with self._semaphore:
                    try:
                        completion = await self._sdk.chat.completions.create(
                            **request, extra_body=extra_body, timeout=timeout_s
                        )
                    except openai.RateLimitError as exc:
                        if _is_daily_quota_error(exc):
                            raise QuotaExceededError(str(exc)) from exc
                        raise
        latency_ms = (time.perf_counter() - start) * 1000

        usage = completion.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        cost = float((usage.model_extra or {}).get("cost") or 0.0) if usage else 0.0
        self.budget.charge(cost, prompt_tokens, completion_tokens)

        choice = completion.choices[0] if completion.choices else None
        response = LLMResponse(
            text=(choice.message.content if choice and choice.message else None) or "",
            model=completion.model or params.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            attempts=attempt.retry_state.attempt_number,
            finish_reason=choice.finish_reason if choice else None,
        )
        if self.cache is not None:
            self.cache.put(key, response.model_dump(exclude={"cached", "latency_ms"}))
        return response
