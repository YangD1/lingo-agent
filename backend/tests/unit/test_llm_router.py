import uuid
from collections.abc import AsyncIterator, Iterator
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
from pydantic import BaseModel, SecretStr

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
    assert model.tags == ["task:chat", f"connection:{kind}"]


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
