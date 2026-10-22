"""Run one async LLM referee on a persistent loop for the synchronous game engine."""

from __future__ import annotations

import asyncio
import threading

from bball3x3.schemas.referee import RefereeDecision, RefereeState

from .llm_referee import LLMReferee, LLMRefereeResult


class SyncLLMReferee:
    """A per-game bridge; use ``close`` after the game, including on errors.

    A persistent loop lets the async HTTP client and its concurrency primitives
    keep one event-loop owner across all events. Game state remains on the
    caller's thread, and each judgement completes before the next transition.
    """

    def __init__(self, referee: LLMReferee, *, close_backend: bool = False) -> None:
        self.referee = referee
        self.close_backend = close_backend
        self.last_result: LLMRefereeResult | None = None
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="bball3x3-llm-referee")
        self._closed = False
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def judge(self, state: RefereeState) -> RefereeDecision:
        if self._closed:
            raise RuntimeError("LLM referee adapter is closed")
        future = asyncio.run_coroutine_threadsafe(self.referee.judge_with_trace(state), self._loop)
        self.last_result = None
        self.last_result = future.result()
        return self.last_result.decision

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.close_backend:
                aclose = getattr(self.referee.backend, "aclose", None)
                if aclose is not None:
                    asyncio.run_coroutine_threadsafe(aclose(), self._loop).result()
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()

    def __enter__(self) -> SyncLLMReferee:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
