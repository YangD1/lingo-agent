"""Structured calls that are retried when the vendor stalls or fails (ADR 0056).

For a task whose params set `resilient: true`:

- A call is **stalled** when the vendor sends nothing for longer than the model usually
  takes (`latency.LatencyStats`): no first chunk, or a gap after one. It is cancelled
  with `STALLED` (recorded as `stalled`) and raises `CallStalledError`.
- Stalls, timeouts, dropped connections, 429 and 5xx are retried with the **same
  request**: at once after a stall, else after 1, 2, 4, 8 s (with jitter) or the
  vendor's `Retry-After`. Other failures go to the next model of the chain at once, as
  without this layer.
- Each retry takes one from the caller's `RetryBudget` (one for a whole practice set);
  none left, the failure is raised. A model that failed twice hands over to the next.
- A model stalled 3 times in 5 minutes is skipped for 5 minutes (`Breaker`), unless
  every model of the chain is.

Tasks without the param run as before (`llm.astream_structured`, `get_structured_llm`).
"""

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import anthropic
import httpx
import openai
from langchain_core.language_models import LanguageModelInput
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from app.providers.config import RESILIENT_PARAM, TenantProviderContext
from app.providers.latency import LatencyKey, LatencyStats, get_latency_stats
from app.providers.llm import (
    RoutedModel,
    StructuredOutputMissingError,
    StructuredPart,
    astream_structured,
    get_routed_models,
    get_structured_llm,
    stream_tool_call,
    structured_parts,
)
from app.usage.recorder import STALLED

logger = logging.getLogger(__name__)

# A model with no timeout of its own: the SDK's default is 600 s, far past any wait.
DEFAULT_TIMEOUT = 120.0
# Retries a call gets when its caller gives no budget.
DEFAULT_RETRIES = 2
# Failures (stalls included) on one model before the next one takes over.
FAILURES_PER_MODEL = 2
BACKOFF_STEPS = (1.0, 2.0, 4.0, 8.0)
# A longer `Retry-After` is not waited for: the next model answers instead.
MAX_RETRY_AFTER = 30.0


class CallStalledError(TimeoutError):
    """The vendor sent nothing for `after` seconds; `chunks` came before."""

    def __init__(self, after: float, chunks: int) -> None:
        super().__init__(f"no output for {after:.0f} s after {chunks} chunks")
        self.after = after
        self.chunks = chunks


@dataclass
class RetryBudget:
    """Retries several calls share, e.g. one practice set's (ADR 0056 §4)."""

    retries: int
    used: int = 0

    def take(self) -> bool:
        if self.used >= self.retries:
            return False
        self.used += 1
        return True


@dataclass(frozen=True, slots=True)
class BreakerRule:
    stalls: int = 3
    within: float = 300.0
    skip_for: float = 300.0


@dataclass
class Breaker:
    """Models that kept stalling, skipped for a while. In-process (ADR 0025)."""

    rule: BreakerRule = field(default_factory=BreakerRule)
    clock: Callable[[], float] = time.monotonic
    _stalls: dict[LatencyKey, deque[float]] = field(default_factory=dict)
    _open_until: dict[LatencyKey, float] = field(default_factory=dict)

    def stalled(self, key: LatencyKey) -> None:
        now = self.clock()
        stalls = self._stalls.setdefault(key, deque(maxlen=self.rule.stalls))
        stalls.append(now)
        if len(stalls) == self.rule.stalls and now - stalls[0] <= self.rule.within:
            self._open_until[key] = now + self.rule.skip_for
            stalls.clear()
            logger.warning("model %s/%s keeps stalling on %s: skipped", *key[1:])

    def is_open(self, key: LatencyKey) -> bool:
        until = self._open_until.get(key)
        if until is None:
            return False
        if until <= self.clock():
            del self._open_until[key]
            return False
        return True

    def clear(self) -> None:
        self._stalls.clear()
        self._open_until.clear()


_breaker = Breaker()


def get_breaker() -> Breaker:
    return _breaker


def is_resilient(ctx: TenantProviderContext, task: str) -> bool:
    routed = get_routed_models(ctx, task)
    return bool(routed and routed[0].resolved.params.get(RESILIENT_PARAM))


def retry_after(exc: BaseException) -> float | None:
    """How long to wait before retrying the same request, or None when retrying it
    won't help (a bad request, a refused key, filtered content, ...)."""
    if isinstance(exc, TimeoutError):  # stalls, StreamChunkTimeoutError
        return 0.0
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in (408, 429) or status >= 500:
            return _header_seconds(exc) or 0.0
        return None
    if isinstance(
        exc, httpx.TransportError | openai.APIConnectionError | anthropic.APIConnectionError
    ):
        return 0.0
    return None


def _header_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    value = headers.get("retry-after") if headers is not None else None
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:  # an HTTP date: rare from model vendors
        return None


def backoff(retry: int, rng: random.Random) -> float:
    """Wait before the `retry`-th retry (1-based) after an error, with ±25% jitter."""
    step = BACKOFF_STEPS[min(retry, len(BACKOFF_STEPS)) - 1]
    return step * rng.uniform(0.75, 1.25)


async def watched[T](
    start: Callable[[], AsyncIterator[T]], first: float, gap: float
) -> AsyncIterator[T]:
    """`start()`'s items, read in a task of its own so a stalled read can be cancelled
    with `STALLED`: nothing within `first` seconds, or `gap` seconds after an item."""
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in start():
                queue.put_nowait(("item", item))
        except Exception as exc:
            queue.put_nowait(("error", exc))
        else:
            queue.put_nowait(("end", None))

    task = asyncio.create_task(pump())
    chunks = 0
    try:
        while True:
            wait = first if chunks == 0 else gap
            try:
                kind, value = await asyncio.wait_for(queue.get(), wait)
            except TimeoutError:
                task.cancel(STALLED)
                await asyncio.wait([task])
                raise CallStalledError(wait, chunks) from None
            if kind == "end":
                return
            if kind == "error":
                raise value
            chunks += 1
            yield value
    finally:
        if not task.done():
            task.cancel()
            await asyncio.wait([task])


@dataclass
class _Attempts:
    """One request's tries over the chain."""

    ctx: TenantProviderContext
    task: str
    budget: RetryBudget
    stats: LatencyStats
    breaker: Breaker
    rng: random.Random
    attempt: int = 0
    retries: int = 0

    def key(self, routed: RoutedModel) -> LatencyKey:
        r = routed.resolved
        return LatencyKey(self.ctx.tenant_id, r.connection, r.model, self.task)

    def chain(self) -> list[RoutedModel]:
        routed = list(get_routed_models(self.ctx, self.task))
        usable = [r for r in routed if not self.breaker.is_open(self.key(r))]
        return usable or routed

    def config(self, config: RunnableConfig | None) -> RunnableConfig:
        self.attempt += 1
        given = config or {}
        return {**given, "metadata": {**given.get("metadata", {}), "attempt": self.attempt}}

    def threshold(self, routed: RoutedModel) -> float:
        configured = float(routed.resolved.params.get("timeout") or DEFAULT_TIMEOUT)
        return self.stats.threshold(self.key(routed), streamed=True, configured=configured)

    async def wait_to_retry(self, exc: Exception, routed: RoutedModel, failures: int) -> bool:
        """Whether to send the request again to the same model, after waiting."""
        if isinstance(exc, CallStalledError):
            self.breaker.stalled(self.key(routed))
        wait = retry_after(exc)
        if wait is None:
            return False
        if failures >= FAILURES_PER_MODEL or wait > MAX_RETRY_AFTER:
            return False
        if not isinstance(exc, TimeoutError):
            wait = max(wait, backoff(self.retries + 1, self.rng))
        if not self.budget.take():
            raise exc
        self.retries += 1
        logger.warning(
            "%s: retrying %s/%s after %s (%.1f s)",
            self.task,
            routed.resolved.connection,
            routed.resolved.model,
            type(exc).__name__,
            wait,
        )
        if wait:
            await asyncio.sleep(wait)
        return True

    def next_model(self, exc: Exception, last: bool) -> None:
        """Hand over to the next model, or raise: a retryable failure needs budget."""
        if last:
            raise exc
        if retry_after(exc) is not None and not self.budget.take():
            raise exc
        logger.warning("%s: next model after %s", self.task, type(exc).__name__)


async def stream_structured[T: BaseModel](
    ctx: TenantProviderContext,
    task: str,
    schema: type[T],
    messages: LanguageModelInput,
    *,
    config: RunnableConfig | None = None,
    budget: RetryBudget | None = None,
    rng: random.Random | None = None,
) -> AsyncIterator[StructuredPart[T]]:
    """`llm.astream_structured`, retried as above until its first part. A failure after
    that raises (`CallStalledError` for a stall): the caller has used the parts, so
    only it can ask for the rest."""
    if not is_resilient(ctx, task):
        async for part in astream_structured(ctx, task, schema, messages, config=config):
            yield part
        return
    async for part in _run(ctx, task, schema, messages, config, budget, rng, restart=False):
        yield part


async def invoke_structured[T: BaseModel](
    ctx: TenantProviderContext,
    task: str,
    schema: type[T],
    messages: LanguageModelInput,
    *,
    config: RunnableConfig | None = None,
    budget: RetryBudget | None = None,
    rng: random.Random | None = None,
) -> T:
    """`get_structured_llm(...).ainvoke`, retried as above. Streamed underneath, so a
    stall is found by its first chunk; a part-written answer is simply asked again."""
    if not is_resilient(ctx, task):
        return await get_structured_llm(ctx, task, schema).ainvoke(messages, config=config)
    async for part in _run(ctx, task, schema, messages, config, budget, rng, restart=True):
        if part.done:
            assert part.output is not None
            return part.output
    raise StructuredOutputMissingError(f"the model returned no {schema.__name__}")


async def _run[T: BaseModel](
    ctx: TenantProviderContext,
    task: str,
    schema: type[T],
    messages: LanguageModelInput,
    config: RunnableConfig | None,
    budget: RetryBudget | None,
    rng: random.Random | None,
    *,
    restart: bool,
) -> AsyncIterator[StructuredPart[T]]:
    tries = _Attempts(
        ctx,
        task,
        budget or RetryBudget(DEFAULT_RETRIES),
        get_latency_stats(),
        get_breaker(),
        rng or random.Random(),
    )
    chain = tries.chain()
    for i, routed in enumerate(chain):
        failures = 0
        while True:
            limit = tries.threshold(routed)
            run = tries.config(config)
            started = False
            try:
                start = partial(stream_tool_call, routed.model, schema, messages, run)
                parts = structured_parts(watched(start, limit, limit), schema)
                async for part in parts:
                    if part.done and part.output is None and restart:
                        raise StructuredOutputMissingError(f"no valid {schema.__name__}")
                    if not restart:
                        started = True
                        yield part
                    elif part.done:
                        yield part
                return
            except Exception as exc:
                if started:
                    if isinstance(exc, CallStalledError):
                        tries.breaker.stalled(tries.key(routed))
                    raise
                failures += 1
                if await tries.wait_to_retry(exc, routed, failures):
                    continue
                tries.next_model(exc, last=i == len(chain) - 1)
                break
