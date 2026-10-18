"""The retry layer for stalled and failing structured calls (ADR 0056)."""

import asyncio
import random
from collections.abc import AsyncIterator, Iterator, Sequence
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr

from app.providers import llm, resilience
from app.providers.config import RESILIENT_PARAM, ResolvedModel, sdk_params
from app.providers.latency import LatencyKey, LatencyStats
from app.providers.llm import RoutedModel, StructuredOutputMissingError
from app.providers.resilience import (
    Breaker,
    BreakerRule,
    CallStalledError,
    RetryBudget,
    backoff,
    retry_after,
)
from app.usage.recorder import UsageLabels, UsageRecord, UsageRecorder
from tests.unit.provider_fixtures import TENANT, make_ctx

CTX = make_ctx()
TASK = "exercise_critic"
PIECES = ['{"first": "a', 'pple", "sec', 'ond": "pear"}']
# Seconds without output that count as stalled here: no latency samples, so the
# configured timeout.
STALL = 0.05


class Items(BaseModel):
    first: str
    second: str


class StatusError(Exception):
    """A vendor's HTTP error, as the SDKs raise it: `status_code` and the response."""

    def __init__(self, status: int, retry_after: str | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status
        headers = {"retry-after": retry_after} if retry_after is not None else {}
        self.response = SimpleNamespace(headers=headers)


class Scripted(BaseChatModel):
    """Does one step of `script` per call (the last one repeats): `ok`, `stall` (before
    any output), `stall_mid` (after the first piece), `text`, `bad` (args that don't fit)
    or an HTTP status."""

    script: list[str]
    calls: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(  # type: ignore[override]
        self, tools: Sequence[Any], *, tool_choice: str | None = None, **kwargs: Any
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        step = self.script[min(len(self.calls), len(self.script) - 1)]
        self.calls.append(step)
        if step == "stall":
            await asyncio.sleep(3600)
        if step.isdigit():
            raise StatusError(int(step))
        if step == "text":
            yield ChatGenerationChunk(message=AIMessageChunk(content="In words, then."))
            return
        pieces = ['{"first": "apple"}'] if step == "bad" else PIECES
        for i, piece in enumerate(pieces):
            if step == "stall_mid" and i == 1:
                await asyncio.sleep(3600)
            chunk = {"name": "Items" if i == 0 else None, "args": piece, "id": "c1", "index": 0}
            message = AIMessageChunk(content="", tool_call_chunks=[chunk])
            yield ChatGenerationChunk(message=message)


def routed(
    name: str, *script: str, records: list[UsageRecord], resilient: bool = True
) -> RoutedModel:
    labels = UsageLabels(TENANT, TASK, name, "m")
    model = Scripted(script=list(script), callbacks=[UsageRecorder(labels, records.append)])
    params: dict[str, Any] = {"timeout": STALL, RESILIENT_PARAM: resilient}
    return RoutedModel(
        model, ResolvedModel(name, "openai_compatible", "m", "https://x/v1", None, params)
    )


@pytest.fixture
def breaker(monkeypatch: pytest.MonkeyPatch) -> Breaker:
    fresh = Breaker()
    monkeypatch.setattr(resilience, "get_breaker", lambda: fresh)
    return fresh


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, breaker: Breaker) -> Iterator[None]:
    monkeypatch.setattr(resilience, "get_latency_stats", LatencyStats)
    monkeypatch.setattr(resilience, "BACKOFF_STEPS", (0.001, 0.002, 0.004, 0.008))
    yield


def use(monkeypatch: pytest.MonkeyPatch, *chain: RoutedModel) -> None:
    monkeypatch.setattr(resilience, "get_routed_models", lambda ctx, task: chain)


def scripted(r: RoutedModel) -> Scripted:
    assert isinstance(r.model, Scripted)
    return r.model


def key(name: str) -> LatencyKey:
    return LatencyKey(TENANT, name, "m", TASK)


async def invoke(budget: RetryBudget) -> Items:
    return await resilience.invoke_structured(
        CTX, TASK, Items, "q", budget=budget, rng=random.Random(0)
    )


async def stream(budget: RetryBudget) -> list[llm.StructuredPart[Items]]:
    return [
        part
        async for part in resilience.stream_structured(
            CTX, TASK, Items, "q", budget=budget, rng=random.Random(0)
        )
    ]


EXPECTED = Items(first="apple", second="pear")


# --- retrying the same request -------------------------------------------------------------


async def test_a_stalled_call_is_sent_again_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    records: list[UsageRecord] = []
    primary = routed("a", "stall", "ok", records=records)
    use(monkeypatch, primary, routed("b", "ok", records=records))
    budget = RetryBudget(10)

    assert await invoke(budget) == EXPECTED
    assert scripted(primary).calls == ["stall", "ok"]
    assert budget.used == 1
    assert [(r.connection_name, r.status, r.attempt) for r in records] == [
        ("a", "stalled", 1),
        ("a", "ok", 2),
    ]


@pytest.mark.parametrize("status", ["429", "500", "503", "408"])
async def test_rate_limits_and_server_errors_are_retried(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    records: list[UsageRecord] = []
    primary = routed("a", status, "ok", records=records)
    use(monkeypatch, primary)
    budget = RetryBudget(10)

    assert await invoke(budget) == EXPECTED
    assert scripted(primary).calls == [status, "ok"]
    assert budget.used == 1


@pytest.mark.parametrize("status", ["400", "401", "403"])
async def test_other_errors_go_to_the_next_model_without_budget(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    records: list[UsageRecord] = []
    primary, backup = routed("a", status, records=records), routed("b", "ok", records=records)
    use(monkeypatch, primary, backup)
    budget = RetryBudget(10)

    assert await invoke(budget) == EXPECTED
    assert (scripted(primary).calls, scripted(backup).calls) == ([status], ["ok"])
    assert budget.used == 0


async def test_an_answer_in_text_or_that_does_not_fit_goes_to_the_next_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[UsageRecord] = []
    chain = (
        routed("a", "text", records=records),
        routed("b", "bad", records=records),
        routed("c", "ok", records=records),
    )
    use(monkeypatch, *chain)
    budget = RetryBudget(10)

    assert await invoke(budget) == EXPECTED
    assert [scripted(r).calls for r in chain] == [["text"], ["bad"], ["ok"]]
    assert budget.used == 0


async def test_a_model_failing_twice_hands_over(monkeypatch: pytest.MonkeyPatch) -> None:
    records: list[UsageRecord] = []
    primary = routed("a", "stall", "503", "ok", records=records)
    backup = routed("b", "ok", records=records)
    use(monkeypatch, primary, backup)
    budget = RetryBudget(10)

    assert await invoke(budget) == EXPECTED
    assert (scripted(primary).calls, scripted(backup).calls) == (["stall", "503"], ["ok"])
    # One retry, one hand-over.
    assert budget.used == 2
    assert [r.attempt for r in records] == [1, 2, 3]


async def test_no_budget_left_raises_without_another_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[UsageRecord] = []
    primary, backup = routed("a", "stall", records=records), routed("b", "ok", records=records)
    use(monkeypatch, primary, backup)
    budget = RetryBudget(1, used=1)

    with pytest.raises(CallStalledError):
        await invoke(budget)
    assert (scripted(primary).calls, scripted(backup).calls) == (["stall"], [])


async def test_the_budget_is_shared_between_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    records: list[UsageRecord] = []
    primary = routed("a", "stall", records=records)
    use(monkeypatch, primary)
    budget = RetryBudget(1)

    results = await asyncio.gather(invoke(budget), invoke(budget), return_exceptions=True)
    assert all(isinstance(r, CallStalledError) for r in results)
    # Two first tries and the one retry left: the other call gets none.
    assert budget.used == 1
    assert len(scripted(primary).calls) == 3


async def test_the_last_model_failing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    records: list[UsageRecord] = []
    use(monkeypatch, routed("a", "500", records=records))

    with pytest.raises(StatusError):
        await invoke(RetryBudget(10))


# --- streams --------------------------------------------------------------------------------


async def test_a_stream_stalled_before_its_first_part_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[UsageRecord] = []
    primary = routed("a", "stall", "ok", records=records)
    use(monkeypatch, primary)

    parts = await stream(RetryBudget(10))
    assert parts[-1].output == EXPECTED
    assert scripted(primary).calls == ["stall", "ok"]


async def test_a_stream_stalled_after_a_part_raises_for_the_caller(
    monkeypatch: pytest.MonkeyPatch, breaker: Breaker
) -> None:
    """The caller has used the first parts: only it can ask for the rest (ADR 0056 §3)."""
    records: list[UsageRecord] = []
    primary, backup = routed("a", "stall_mid", records=records), routed("b", "ok", records=records)
    use(monkeypatch, primary, backup)
    budget = RetryBudget(10)
    seen: list[dict[str, Any]] = []

    with pytest.raises(CallStalledError) as raised:
        async for part in resilience.stream_structured(CTX, TASK, Items, "q", budget=budget):
            seen.append(part.args)
    assert seen == [{"first": "a"}]
    assert raised.value.chunks == 1
    assert scripted(backup).calls == [] and budget.used == 0
    assert [r.status for r in records] == ["stalled"]
    assert breaker._stalls[key("a")]


async def test_a_part_written_answer_is_simply_asked_again_when_invoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[UsageRecord] = []
    primary = routed("a", "stall_mid", "ok", records=records)
    use(monkeypatch, primary)

    assert await invoke(RetryBudget(10)) == EXPECTED
    assert scripted(primary).calls == ["stall_mid", "ok"]


async def test_cancelling_the_caller_records_a_cancelled_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[UsageRecord] = []
    primary = routed("a", "stall", records=records)
    # Long enough that only the caller ends it.
    primary.resolved.params["timeout"] = 30
    use(monkeypatch, primary)

    task = asyncio.create_task(invoke(RetryBudget(10)))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [r.status for r in records] == ["cancelled"]


# --- the stall threshold comes from the model's usual speed --------------------------------


async def test_the_threshold_follows_the_models_first_chunk_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = LatencyStats()
    for _ in range(20):
        stats.observe(key("a"), 5000, 1000)
    monkeypatch.setattr(resilience, "get_latency_stats", lambda: stats)
    records: list[UsageRecord] = []
    primary = routed("a", "ok", records=records)
    primary.resolved.params["timeout"] = 120
    use(monkeypatch, primary)
    seen: list[float] = []
    real = resilience.watched

    def spy(start: Any, first: float, gap: float) -> Any:
        seen.append(first)
        return real(start, first, gap)

    monkeypatch.setattr(resilience, "watched", spy)
    await invoke(RetryBudget(10))
    # p95 1 s x 3 = 3 s, under the 20 s floor.
    assert seen == [20.0]


# --- circuit breaker -----------------------------------------------------------------------


def test_the_breaker_opens_after_three_stalls_within_five_minutes() -> None:
    now = [0.0]
    breaker = Breaker(BreakerRule(stalls=3, within=300, skip_for=300), clock=lambda: now[0])
    for t in (0, 100, 200):
        now[0] = t
        assert not breaker.is_open(key("a"))
        breaker.stalled(key("a"))
    assert breaker.is_open(key("a"))
    now[0] = 499
    assert breaker.is_open(key("a"))
    now[0] = 500
    assert not breaker.is_open(key("a"))


def test_stalls_spread_out_do_not_open_the_breaker() -> None:
    now = [0.0]
    breaker = Breaker(BreakerRule(stalls=3, within=300, skip_for=300), clock=lambda: now[0])
    for t in (0, 200, 400, 600):
        now[0] = t
        breaker.stalled(key("a"))
    assert not breaker.is_open(key("a"))


async def test_a_skipped_model_is_not_called(
    monkeypatch: pytest.MonkeyPatch, breaker: Breaker
) -> None:
    records: list[UsageRecord] = []
    primary, backup = routed("a", "ok", records=records), routed("b", "ok", records=records)
    use(monkeypatch, primary, backup)
    for _ in range(3):
        breaker.stalled(key("a"))

    assert await invoke(RetryBudget(10)) == EXPECTED
    assert (scripted(primary).calls, scripted(backup).calls) == ([], ["ok"])


async def test_every_model_skipped_uses_the_chain_anyway(
    monkeypatch: pytest.MonkeyPatch, breaker: Breaker
) -> None:
    records: list[UsageRecord] = []
    primary = routed("a", "ok", records=records)
    use(monkeypatch, primary)
    for _ in range(3):
        breaker.stalled(key("a"))

    assert await invoke(RetryBudget(10)) == EXPECTED
    assert scripted(primary).calls == ["ok"]


# --- tasks without the param ----------------------------------------------------------------


async def test_a_task_without_the_param_runs_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    records: list[UsageRecord] = []
    plain = routed("a", "stall", records=records, resilient=False)
    use(monkeypatch, plain)
    monkeypatch.setattr(llm, "get_chat_models", lambda ctx, task: (plain.model,))
    calls: list[str] = []

    class Done(Exception):
        pass

    def structured(ctx: Any, task: str, schema: Any) -> Any:
        calls.append(task)
        raise Done

    monkeypatch.setattr(resilience, "get_structured_llm", structured)
    with pytest.raises(Done):
        await invoke(RetryBudget(10))
    assert calls == [TASK]


# --- classification and waits ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "wait"),
    [
        (CallStalledError(30, 0), 0.0),
        (TimeoutError(), 0.0),
        (StatusError(429, "3"), 3.0),
        (StatusError(429, "Wed, 21 Oct 2026 07:28:00 GMT"), 0.0),
        (StatusError(503), 0.0),
        (StatusError(400), None),
        (StatusError(401), None),
        (httpx.ConnectError("refused"), 0.0),
        (StructuredOutputMissingError("text"), None),
        (ValueError("bug"), None),
    ],
)
def test_which_failures_are_retried(exc: BaseException, wait: float | None) -> None:
    assert retry_after(exc) == wait


def test_backoff_doubles_up_to_eight_seconds_with_jitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resilience, "BACKOFF_STEPS", (1.0, 2.0, 4.0, 8.0))
    rng = random.Random(1)
    for retry, step in [(1, 1), (2, 2), (3, 4), (4, 8), (7, 8)]:
        assert step * 0.75 <= backoff(retry, rng) <= step * 1.25


def test_retry_after_longer_than_the_cap_hands_over() -> None:
    assert retry_after(StatusError(429, "120")) == 120.0
    assert resilience.MAX_RETRY_AFTER < 120


# --- building the models -------------------------------------------------------------------


def test_the_param_never_reaches_the_sdk() -> None:
    assert sdk_params({"timeout": 120, RESILIENT_PARAM: True}) == {"timeout": 120}


@pytest.mark.parametrize("resilient", [True, False])
def test_resilient_models_get_no_hidden_sdk_retry(resilient: bool) -> None:
    params: dict[str, Any] = {"timeout": 120, "max_retries": 1}
    if resilient:
        params[RESILIENT_PARAM] = True
    model = llm.build_chat_model(
        ResolvedModel("a", "openai_compatible", "m", "https://x/v1", SecretStr("k"), params),
        TASK,
    )
    assert isinstance(model, ChatOpenAI)
    assert model.max_retries == (0 if resilient else 1)
    assert (model.stream_chunk_timeout is None) == resilient
