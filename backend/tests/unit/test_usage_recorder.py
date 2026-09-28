import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import anyio
import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.output_parsers import StrOutputParser
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableConfig, RunnableLambda
from pydantic import SecretStr

from app.providers import llm
from app.providers.config import ResolvedModel
from app.usage import recorder as usage_recorder
from app.usage.recorder import UsageLabels, UsageRecord, UsageRecorder
from tests.unit.provider_fixtures import TENANT, conn, make_config, make_ctx

USER = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
CONVERSATION = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
PROMPT = "my secret diary entry"


class ProviderDown(Exception):
    pass


def usage(input_tokens: int, output_tokens: int) -> UsageMetadata:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


class MeteredChatModel(BaseChatModel):
    """Reports token usage like real providers do: on the message, or on the last chunk."""

    fail: bool = False

    @property
    def _llm_type(self) -> str:
        return "metered"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.fail:
            raise ProviderDown(f"upstream rejected: {messages[-1].content}")
        message = AIMessage("reply", usage_metadata=usage(7, 3))
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        if self.fail:
            raise ProviderDown
        yield ChatGenerationChunk(message=AIMessageChunk(content="re"))
        yield ChatGenerationChunk(message=AIMessageChunk(content="ply"))
        # OpenAI's `stream_options.include_usage` sends usage in a final, empty chunk.
        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=usage(11, 5)))


def metered(
    records: list[UsageRecord], *, fail: bool = False, is_fallback: bool = False, model: str = "m1"
) -> MeteredChatModel:
    labels = UsageLabels(TENANT, "chat", "openai", model, is_fallback=is_fallback)
    return MeteredChatModel(fail=fail, callbacks=[UsageRecorder(labels, records.append)])


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    llm.reset_caches()
    yield
    llm.reset_caches()


def ids_metadata() -> RunnableConfig:
    return {"metadata": {"user_id": str(USER), "conversation_id": str(CONVERSATION)}}


async def test_invoke_records_tokens_and_ids() -> None:
    records: list[UsageRecord] = []
    await metered(records).ainvoke([HumanMessage(PROMPT)], config=ids_metadata())

    [record] = records
    assert record.tenant_id == TENANT
    assert (record.user_id, record.conversation_id) == (USER, CONVERSATION)
    assert (record.task, record.connection_name, record.model) == ("chat", "openai", "m1")
    assert (record.input_tokens, record.output_tokens) == (7, 3)
    assert (record.status, record.error_code, record.is_fallback) == ("ok", None, False)
    assert record.latency_ms >= 0


async def test_stream_records_usage_from_final_chunk() -> None:
    records: list[UsageRecord] = []
    chunks = [c async for c in metered(records).astream([HumanMessage(PROMPT)])]

    assert "".join(str(c.content) for c in chunks) == "reply"
    [record] = records
    assert (record.input_tokens, record.output_tokens, record.status) == (11, 5, "ok")


async def test_missing_or_invalid_ids_are_recorded_as_null() -> None:
    records: list[UsageRecord] = []
    model = metered(records)
    await model.ainvoke([HumanMessage(PROMPT)])
    await model.ainvoke([HumanMessage(PROMPT)], config={"metadata": {"user_id": "not-a-uuid"}})

    assert [(r.user_id, r.conversation_id) for r in records] == [(None, None), (None, None)]


async def test_langgraph_thread_id_is_the_conversation_id() -> None:
    records: list[UsageRecord] = []
    await metered(records).ainvoke(
        [HumanMessage(PROMPT)], config={"metadata": {"thread_id": str(CONVERSATION)}}
    )

    assert records[0].conversation_id == CONVERSATION


async def test_ids_reach_a_model_nested_inside_a_chain() -> None:
    records: list[UsageRecord] = []

    def to_messages(text: str) -> list[BaseMessage]:
        return [HumanMessage(text)]

    chain = RunnableLambda(to_messages) | metered(records) | StrOutputParser()

    assert await chain.ainvoke(PROMPT, config=ids_metadata()) == "reply"
    assert [(r.user_id, r.conversation_id) for r in records] == [(USER, CONVERSATION)]


async def test_error_records_class_name_but_no_content() -> None:
    records: list[UsageRecord] = []
    with pytest.raises(ProviderDown):
        await metered(records, fail=True).ainvoke([HumanMessage(PROMPT)])

    [record] = records
    assert (record.status, record.error_code) == ("error", "ProviderDown")
    assert (record.input_tokens, record.output_tokens) == (0, 0)
    assert PROMPT not in repr(record)


class StallingChatModel(BaseChatModel):
    """Streams one chunk, then stalls (a slow provider) until cancelled."""

    @property
    def _llm_type(self) -> str:
        return "stalling"

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
        yield ChatGenerationChunk(message=AIMessageChunk(content="Hel"))
        await asyncio.sleep(10)
        yield ChatGenerationChunk(message=AIMessageChunk(content="lo"))


async def test_cancelled_stream_is_recorded_under_anyio_cancellation() -> None:
    """A client disconnect cancels the SSE producer through an anyio cancel scope.

    anyio cancellation is level-triggered: every await that suspends inside the
    cancelled scope raises again, including langchain-core's `asyncio.gather` over
    non-inline handlers in its `on_llm_error` dispatch. The recorder must still run.
    """
    records: list[UsageRecord] = []
    labels = UsageLabels(TENANT, "chat", "openai", "m1")
    model = StallingChatModel(callbacks=[UsageRecorder(labels, records.append)])

    with anyio.move_on_after(0.05):
        async for _ in model.astream([HumanMessage(PROMPT)]):
            pass

    assert [(r.status, r.error_code) for r in records] == [("error", "CancelledError")]


async def test_fallback_chain_records_failure_and_backup() -> None:
    records: list[UsageRecord] = []
    chain = llm.chain_with_fallbacks(
        [
            metered(records, fail=True, model="primary"),
            metered(records, is_fallback=True, model="backup"),
        ]
    )
    await chain.ainvoke([HumanMessage(PROMPT)], config=ids_metadata())

    assert [(r.model, r.status, r.is_fallback, r.user_id) for r in records] == [
        ("primary", "error", False, USER),
        ("backup", "ok", True, USER),
    ]


async def test_broken_sink_never_breaks_the_call() -> None:
    def explode(_: UsageRecord) -> None:
        raise RuntimeError("queue gone")

    labels = UsageLabels(TENANT, "chat", "openai", "m1")
    model = MeteredChatModel(callbacks=[UsageRecorder(labels, explode)])

    assert (await model.ainvoke([HumanMessage(PROMPT)])).content == "reply"


async def test_records_go_to_the_installed_sink() -> None:
    records: list[UsageRecord] = []
    labels = UsageLabels(TENANT, "chat", "openai", "m1")
    model = MeteredChatModel(callbacks=[usage_recorder.make_recorder(labels)])

    await model.ainvoke([HumanMessage(PROMPT)])  # no sink installed: dropped silently
    usage_recorder.set_usage_sink(records.append)
    try:
        await model.ainvoke([HumanMessage(PROMPT)])
    finally:
        usage_recorder.set_usage_sink(None)

    assert len(records) == 1


def test_chain_models_carry_recorders_with_their_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "get_providers_config", make_config)
    ctx = make_ctx(conn("deepseek"), conn("openai"))

    models = llm.get_chat_models(ctx, "summarize")  # default route: deepseek, then openai

    labels = []
    for model in models:
        assert isinstance(model.callbacks, list)
        [handler] = model.callbacks
        assert isinstance(handler, UsageRecorder)
        labels.append(handler.labels)
    assert labels == [
        UsageLabels(TENANT, "summarize", "deepseek", "deepseek-chat", is_fallback=False),
        UsageLabels(TENANT, "summarize", "openai", "gpt-5-mini", is_fallback=True),
    ]


def resolved(kind: str, **params: Any) -> ResolvedModel:
    return ResolvedModel(
        connection=kind,
        kind=kind,  # type: ignore[arg-type]
        model="m",
        base_url="https://example.com/v1",
        api_key=SecretStr("sk-test"),
        params=params,
    )


@pytest.mark.parametrize("kind", ["openai", "deepseek", "openai_compatible", "anthropic"])
def test_stream_usage_is_on_by_default(kind: str) -> None:
    # ChatOpenAI would leave it off because we pass our own base_url and client.
    model = llm.build_chat_model(resolved(kind), task="chat")
    assert getattr(model, "stream_usage") is True  # noqa: B009


def test_stream_usage_can_be_switched_off_per_connection() -> None:
    model = llm.build_chat_model(resolved("openai_compatible", stream_usage=False), task="chat")
    assert getattr(model, "stream_usage") is False  # noqa: B009
