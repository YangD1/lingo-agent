import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import httpx2
import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.load import dumps
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda, RunnableWithFallbacks
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr

from app.providers import llm
from app.providers.clients import GuardedChatAnthropic
from app.providers.config import ResolvedModel
from tests.unit.provider_fixtures import TENANT, conn, make_config, make_ctx


class ProviderDown(Exception):
    pass


class ScriptedChatModel(BaseChatModel):
    """Streams `chunks`; raises ProviderDown after `fail_after` chunks (0 = before any)."""

    chunks: list[str]
    fail_after: int | None = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.fail_after is not None:
            raise ProviderDown
        return ChatResult(generations=[ChatGeneration(message=AIMessage("".join(self.chunks)))])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for i, text in enumerate(self.chunks):
            if i == self.fail_after:
                raise ProviderDown
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))
        if self.fail_after is not None and self.fail_after >= len(self.chunks):
            raise ProviderDown

    def with_structured_output(  # type: ignore[override]
        self, schema: type[BaseModel], **kwargs: Any
    ) -> Runnable[LanguageModelInput, BaseModel]:
        def parse(_: Any) -> BaseModel:
            if self.fail_after is not None:
                raise ProviderDown
            return schema.model_validate({"answer": "".join(self.chunks)})

        return RunnableLambda(parse)


def up(*chunks: str) -> ScriptedChatModel:
    return ScriptedChatModel(chunks=list(chunks))


def down(*chunks: str, after: int = 0) -> ScriptedChatModel:
    return ScriptedChatModel(chunks=list(chunks), fail_after=after)


class Answer(BaseModel):
    answer: str


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    llm.reset_caches()
    yield
    llm.reset_caches()


CTX = make_ctx(conn("openai"))


def use_models(monkeypatch: pytest.MonkeyPatch, *models: BaseChatModel) -> None:
    monkeypatch.setattr(llm, "get_chat_models", lambda ctx, task: models)


# --- fallback semantics ---------------------------------------------------------------


async def test_invoke_falls_back_when_primary_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    use_models(monkeypatch, down("x"), up("from ", "backup"))
    result = await llm.get_llm(CTX, "chat").ainvoke("hi")
    assert result.content == "from backup"


async def test_stream_falls_back_if_primary_fails_before_first_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_models(monkeypatch, down("a", "b", after=0), up("from ", "backup"))
    # langchain-core ends every stream with an empty "last" chunk; ignore it.
    chunks = [c.content async for c in llm.get_llm(CTX, "chat").astream("hi") if c.content]
    assert chunks == ["from ", "backup"]


async def test_stream_error_after_first_chunk_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_models(monkeypatch, down("par", "tial", after=1), up("backup"))
    received: list[str | list[str | dict[str, Any]]] = []
    with pytest.raises(ProviderDown):
        async for chunk in llm.get_llm(CTX, "chat").astream("hi"):
            received.append(chunk.content)
    # The backup never runs: mixing two models' output in one reply would be worse.
    assert received == ["par"]


async def test_all_models_failing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    use_models(monkeypatch, down("x"), down("y"))
    with pytest.raises(ProviderDown):
        await llm.get_llm(CTX, "chat").ainvoke("hi")


def test_single_model_is_returned_without_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    only = up("x")
    use_models(monkeypatch, only)
    assert llm.get_llm(CTX, "chat") is only


async def test_structured_output_binds_schema_on_every_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_models(monkeypatch, down("x"), up("42"))
    result = await llm.get_structured_llm(CTX, "extract", Answer).ainvoke("q")
    assert result == Answer(answer="42")


def test_get_chat_model_returns_primary_only(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = up("x")
    use_models(monkeypatch, primary, up("y"))
    assert llm.get_chat_model(CTX, "chat") is primary


# --- construction ----------------------------------------------------------------------


def resolved(kind: Any, connection: str, model: str, **extra: Any) -> ResolvedModel:
    return ResolvedModel(
        connection=connection,
        kind=kind,
        model=model,
        base_url=extra.pop("base_url", f"https://{connection}.example.com/v1"),
        api_key=extra.pop("api_key", SecretStr("sk-test-secret")),
        params={"timeout": 30, "max_retries": 1, **extra},
    )


@pytest.mark.parametrize(
    ("kind", "cls"),
    [("deepseek", ChatDeepSeek), ("anthropic", GuardedChatAnthropic), ("openai", ChatOpenAI)],
)
def test_build_chat_model_picks_integration(kind: str, cls: type[BaseChatModel]) -> None:
    model = llm.build_chat_model(resolved(kind, kind, "some-model"), task="chat")
    assert type(model) is cls
    assert model.tags == ["task:chat", f"connection:{kind}", f"kind:{kind}"]


def test_openai_family_gets_guarded_async_and_blocked_sync_clients() -> None:
    model = llm.build_chat_model(resolved("deepseek", "deepseek", "deepseek-chat"), task="chat")
    assert isinstance(model, ChatDeepSeek)
    assert isinstance(model.http_async_client, httpx2.AsyncClient)
    assert model.http_async_client.follow_redirects is False
    with pytest.raises(RuntimeError, match="sync model calls are disabled"):
        model.invoke("hi")


def test_base_url_is_explicit_even_if_env_says_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://169.254.169.254/latest")
    monkeypatch.setenv("DEEPSEEK_API_BASE", "http://169.254.169.254/latest")
    openai_model = llm.build_chat_model(resolved("openai", "openai", "m"), task="chat")
    deepseek_model = llm.build_chat_model(resolved("deepseek", "deepseek", "m"), task="chat")
    assert isinstance(openai_model, ChatOpenAI) and isinstance(deepseek_model, ChatDeepSeek)
    assert openai_model.openai_api_base == "https://openai.example.com/v1"
    assert deepseek_model.api_base == "https://deepseek.example.com/v1"


def test_custom_anthropic_endpoint() -> None:
    spec = resolved("anthropic", "relay", "claude-sonnet-5", base_url="https://relay.example.com")
    model = llm.build_chat_model(spec, task="chat")
    assert isinstance(model, GuardedChatAnthropic)
    assert str(model._async_client.base_url).rstrip("/") == "https://relay.example.com"


def test_keyless_openai_compatible_gets_placeholder_key() -> None:
    spec = resolved("openai_compatible", "ollama", "qwen3", api_key=None)
    model = llm.build_chat_model(spec, task="chat")
    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_key is not None


@pytest.mark.parametrize("kind", ["deepseek", "anthropic", "openai"])
def test_api_key_not_in_repr_or_serialization(kind: str) -> None:
    model = llm.build_chat_model(resolved(kind, kind, "m"), task="chat")
    assert "sk-test-secret" not in repr(model)
    assert "sk-test-secret" not in dumps(model)


# --- per-tenant caching -------------------------------------------------------------------


def test_models_cached_per_tenant_task_and_version(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config()
    monkeypatch.setattr(llm, "get_providers_config", lambda: config)
    ctx = make_ctx(conn("deepseek"), conn("openai"))

    first = llm.get_chat_models(ctx, "chat")
    assert llm.get_chat_models(ctx, "chat") is first  # same version -> cached
    assert llm.get_chat_models(ctx, "other") is not first  # different task

    edited = make_ctx(conn("deepseek"), conn("openai"), version="v2")
    assert llm.get_chat_models(edited, "chat") is not first  # tenant edited config

    other_tenant = make_ctx(conn("deepseek"), conn("openai"))
    object.__setattr__(other_tenant, "tenant_id", uuid.uuid4())
    assert llm.get_chat_models(other_tenant, "chat") is not first


def test_get_llm_builds_chain_from_tenant_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config()
    monkeypatch.setattr(llm, "get_providers_config", lambda: config)

    chain = llm.get_llm(make_ctx(conn("deepseek"), conn("openai")), "default")
    assert isinstance(chain, RunnableWithFallbacks)
    assert isinstance(chain.runnable, ChatDeepSeek)
    assert [type(f) for f in chain.fallbacks] == [ChatOpenAI]

    only_openai = llm.get_llm(make_ctx(conn("openai"), version="v2"), "default")
    assert isinstance(only_openai, ChatOpenAI)
    assert TENANT is not None


@pytest.mark.parametrize(
    ("kind", "base_url", "level", "expected"),
    [
        ("openai_compatible", "https://relay.example.com/v1", "off", {"reasoning_effort": "none"}),
        ("openai", "https://api.openai.com/v1", "low", {"reasoning_effort": "low"}),
        (
            "openai_compatible",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "off",
            {"extra_body": {"enable_thinking": False}},
        ),
        (
            "openai_compatible",
            "https://api.siliconflow.cn/v1",
            "high",
            {"extra_body": {"enable_thinking": True}},
        ),
        ("anthropic", "https://api.anthropic.com", "off", {}),
        ("deepseek", "https://api.deepseek.com/v1", "low", {}),
        ("openai_compatible", "https://relay.example.com/v1", None, {}),
    ],
)
def test_reasoning_becomes_the_vendors_own_parameter(
    kind: str, base_url: str, level: str | None, expected: dict[str, Any]
) -> None:
    extra = {} if level is None else {"reasoning": level}
    assert llm.reasoning_kwargs(resolved(kind, "c", "m", base_url=base_url, **extra)) == expected


def test_reasoning_reaches_the_sdk_only_translated() -> None:
    spec = resolved("openai_compatible", "relay", "m", reasoning="low")
    relay = llm.build_chat_model(spec, "chat")
    assert isinstance(relay, ChatOpenAI)
    assert relay.reasoning_effort == "low"
    qwen = resolved(
        "openai_compatible",
        "qwen",
        "qwen-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        reasoning="off",
    )
    model = llm.build_chat_model(qwen, "chat")
    assert isinstance(model, ChatOpenAI)
    assert model.extra_body == {"enable_thinking": False}
    assert model.reasoning_effort is None
    # Anthropic's constructor would reject an unknown `reasoning` kwarg.
    llm.build_chat_model(resolved("anthropic", "anthropic", "m", reasoning="off"), "chat")


# --- streamed structured output (ADR 0048) ---------------------------------------------


class ToolStreamModel(BaseChatModel):
    """Streams `pieces` as the arguments of one tool call (or as text with `as_text`);
    raises ProviderDown after `fail_after` pieces."""

    pieces: list[str]
    fail_after: int | None = None
    as_text: bool = False
    bound: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "tool-stream"

    def bind_tools(  # type: ignore[override]
        self, tools: Sequence[Any], *, tool_choice: str | None = None, **kwargs: Any
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        self.bound.append((list(tools), tool_choice))
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
        for i, piece in enumerate(self.pieces):
            if i == self.fail_after:
                raise ProviderDown
            if self.as_text:
                message = AIMessageChunk(content=piece)
            else:
                message = AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {"name": "Items" if i == 0 else None, "args": piece, "id": "c1", "index": 0}
                    ],
                )
            yield ChatGenerationChunk(message=message)


class Items(BaseModel):
    first: str
    second: str


PIECES = ['{"first": "a', 'pple", "sec', 'ond": "pear"}']


async def collect() -> list[llm.StructuredPart[Items]]:
    return [part async for part in llm.astream_structured(CTX, "extract", Items, "q")]


async def test_structured_stream_gives_the_args_as_they_are_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ToolStreamModel(pieces=PIECES)
    use_models(monkeypatch, model)
    parts = await collect()
    assert [p.args for p in parts if not p.done] == [
        {"first": "a"},
        {"first": "apple"},
        {"first": "apple", "second": "pear"},
    ]
    assert parts[-1] == llm.StructuredPart(
        {"first": "apple", "second": "pear"}, Items(first="apple", second="pear"), done=True
    )
    # The schema is forced as a tool call.
    assert model.bound == [([Items], "Items")]


async def test_structured_stream_args_that_do_not_fit_end_without_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_models(monkeypatch, ToolStreamModel(pieces=['{"first": "apple"}']))
    last = (await collect())[-1]
    assert last.done and last.output is None and last.args == {"first": "apple"}


async def test_structured_stream_falls_back_before_its_first_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_models(
        monkeypatch,
        ToolStreamModel(pieces=PIECES, fail_after=0),
        ToolStreamModel(pieces=["I would rather say it in words."], as_text=True),
        ToolStreamModel(pieces=PIECES),
    )
    parts = await collect()
    assert parts[-1].output == Items(first="apple", second="pear")


async def test_structured_stream_failing_after_its_first_part_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, backup = ToolStreamModel(pieces=PIECES, fail_after=2), ToolStreamModel(pieces=PIECES)
    use_models(monkeypatch, first, backup)
    seen: list[dict[str, Any]] = []
    with pytest.raises(ProviderDown):
        async for part in llm.astream_structured(CTX, "extract", Items, "q"):
            seen.append(part.args)
    # The backup never runs: two models' items in one set would not fit together.
    assert seen == [{"first": "a"}, {"first": "apple"}]


async def test_structured_stream_answered_in_text_by_every_model_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_models(monkeypatch, ToolStreamModel(pieces=["No."], as_text=True))
    with pytest.raises(llm.StructuredOutputMissingError):
        await collect()
