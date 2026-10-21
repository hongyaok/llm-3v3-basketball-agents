import asyncio
import os
import time
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

    async def aclose(self) -> None:
        """Close the underlying async HTTP client after the last referee call."""
        await self._sdk.close()

    async def complete(
        self,
        messages: Messages,
        params: CallParams,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        request = self._build_request(messages, params, response_format)
        key = request_key(request)
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return LLMResponse(**{**hit, "cached": True, "latency_ms": 0.0})

        self.budget.check()
        max_retries = getattr(params, "max_retries", DEFAULT_MAX_RETRIES)
        timeout_s = getattr(params, "timeout_s", DEFAULT_TIMEOUT_S)
        extra_body = {"usage": {"include": True}}
        if self.cfg.provider.routing:
            extra_body["provider"] = self.cfg.provider.routing

        start = time.perf_counter()
        retryer = AsyncRetrying(
            retry=retry_if_exception_type(TRANSIENT_ERRORS),
            stop=stop_after_attempt(max_retries + 1),
            wait=wait_exponential(multiplier=self.retry_wait_s, max=30),
            reraise=True,
        )
        async for attempt in retryer:
            with attempt:
                # hold a slot only while a request is in flight, not during backoff
                async with self._semaphore:
                    completion = await self._sdk.chat.completions.create(
                        **request, extra_body=extra_body, timeout=timeout_s
                    )
        latency_ms = (time.perf_counter() - start) * 1000

        usage = completion.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        cost = float((usage.model_extra or {}).get("cost") or 0.0) if usage else 0.0
        self.budget.charge(cost, prompt_tokens, completion_tokens)

        response = LLMResponse(
            text=completion.choices[0].message.content or "",
            model=completion.model or params.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            attempts=attempt.retry_state.attempt_number,
        )
        if self.cache is not None:
            self.cache.put(key, response.model_dump(exclude={"cached", "latency_ms"}))
        return response
