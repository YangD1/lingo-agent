"""Tenant-scoped, task-routed chat models with fallback chains (ADR 0002 + 0004).

Business code asks for a *task* in the context of a tenant, never a model name:

    ctx = await load_provider_context(session, tenant.id)
    reply = await get_llm(ctx, "chat").ainvoke(messages)
    parsed = await get_structured_llm(ctx, "memory_extract", MemorySchema).ainvoke(messages)
    async for part in astream_structured(ctx, "exercise_generate", Items, messages): ...
"""

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

from langchain.chat_models import init_chat_model
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda
from pydantic import BaseModel, ValidationError

from app.providers.cache import TTLCache
from app.providers.clients import GuardedChatAnthropic, UsageOnceChatOpenAI
from app.providers.config import (
    REASONING_PARAM,
    ProvidersConfig,
    ResolvedModel,
    TenantProviderContext,
    load_providers_config,
    resolve_route,
    sdk_params,
)
from app.providers.net_guard import make_async_http_client, make_blocked_sync_client
from app.providers.reasoning_catalog import WithoutReasoningRetry, reasoning_spec
from app.settings import get_settings
from app.usage.recorder import UsageLabels, make_recorder

logger = logging.getLogger(__name__)

# ChatOpenAI refuses to start without a key; keyless OpenAI-compatible servers ignore it.
_KEYLESS_PLACEHOLDER = "not-needed"

# Keyed by (tenant, task, context version): editing a connection or route changes the
# version, so stale models are never served; TTL bounds how long evicted tenants linger.
_models: TTLCache[tuple[object, ...], tuple[BaseChatModel, ...]] = TTLCache(
    maxsize=256, ttl_seconds=600
)


@lru_cache
def get_providers_config() -> ProvidersConfig:
    return load_providers_config(get_settings().providers_config_path)


def reasoning_kwargs(resolved: ResolvedModel) -> dict[str, Any]:
    """The vendor's own parameter for the `reasoning` param, only where this model takes
    that level (task 91, providers/reasoning_catalog.py)."""
    spec = reasoning_spec(resolved.kind, resolved.base_url, resolved.model)
    return spec.kwargs(resolved.params.get(REASONING_PARAM))


def build_chat_model(
    resolved: ResolvedModel,
    task: str,
    *,
    callbacks: list[BaseCallbackHandler] | None = None,
) -> BaseChatModel:
    reasoning = reasoning_kwargs(resolved)
    params: dict[str, Any] = sdk_params(resolved.params) | reasoning
    http_client = make_async_http_client(
        allow_private=get_settings().provider_allow_private_networks,
        timeout=params.get("timeout"),
        wrap=WithoutReasoningRetry if reasoning else None,
    )
    kwargs: dict[str, Any] = {
        # ChatOpenAI only turns this on by itself for the default base URL *and* client,
        # and we always pass both, so without it streamed calls report no token usage.
        # A tenant can switch it off for servers that reject `stream_options`.
        "stream_usage": True,
        **params,
        # Always explicit: otherwise SDKs read OPENAI_BASE_URL / DEEPSEEK_API_BASE / ...
        "base_url": resolved.base_url,
        # Also read back by get_structured_llm (the kind picks the structured-output method).
        "tags": [f"task:{task}", f"connection:{resolved.connection}", f"kind:{resolved.kind}"],
        "callbacks": callbacks,
    }
    if resolved.api_key is not None:
        kwargs["api_key"] = resolved.api_key.get_secret_value()
    elif resolved.kind == "openai_compatible":
        kwargs["api_key"] = _KEYLESS_PLACEHOLDER

    if resolved.kind == "anthropic":
        return GuardedChatAnthropic(model=resolved.model, **kwargs).with_http_client(http_client)

    if resolved.kind in ("openai", "openai_compatible"):
        # openai_compatible is just the OpenAI client pointed at another base_url.
        return UsageOnceChatOpenAI(
            model=resolved.model,
            http_async_client=http_client,
            http_client=make_blocked_sync_client(),
            **kwargs,
        )
    model = init_chat_model(
        resolved.model,
        model_provider=resolved.kind,
        http_async_client=http_client,
        http_client=make_blocked_sync_client(),
        **kwargs,
    )
    if not isinstance(model, BaseChatModel):  # only happens with configurable_fields
        raise TypeError(f"expected BaseChatModel, got {type(model).__name__}")
    return model


def get_chat_models(ctx: TenantProviderContext, task: str) -> tuple[BaseChatModel, ...]:
    """All usable models for a task, primary first. Raises NoModelConfiguredError."""
    resolved = resolve_route(get_providers_config(), ctx, "llm", task)
    return _models.get_or_create(
        (ctx.tenant_id, task, ctx.version),
        lambda: tuple(
            build_chat_model(
                r,
                task,
                callbacks=[
                    make_recorder(
                        UsageLabels(
                            ctx.tenant_id,
                            task,
                            r.connection,
                            r.model,
                            is_fallback=i > 0,
                            billed_tenant_id=r.billed_tenant_id,
                        )
                    )
                ],
            )
            for i, r in enumerate(resolved)
        ),
    )


def chain_with_fallbacks[I, O](runnables: list[Runnable[I, O]]) -> Runnable[I, O]:
    primary, *fallbacks = runnables
    return primary.with_fallbacks(fallbacks) if fallbacks else primary


def get_llm(ctx: TenantProviderContext, task: str) -> Runnable[LanguageModelInput, BaseMessage]:
    """Chat model for `task` with its fallback chain.

    When streaming, a fallback only takes over if the failing model errors before its
    first chunk; errors after output has started propagate to the caller.
    """
    return chain_with_fallbacks(list(get_chat_models(ctx, task)))


def get_llm_with_tools(
    ctx: TenantProviderContext, task: str, tools: Sequence[type[BaseModel]]
) -> Runnable[LanguageModelInput, BaseMessage]:
    """Like get_llm, with `tools` bound to *each* model before chaining (ADR 0015 §2).

    A model class without tool calling stays in the chain unbound: it answers in text.
    """
    return chain_with_fallbacks([_with_tools(model, tools) for model in get_chat_models(ctx, task)])


def _with_tools(
    model: BaseChatModel, tools: Sequence[type[BaseModel]]
) -> Runnable[LanguageModelInput, BaseMessage]:
    try:
        return cast(Runnable[LanguageModelInput, BaseMessage], model.bind_tools(list(tools)))
    except NotImplementedError:
        return model


class StructuredOutputMissingError(Exception):
    """A structured call got no output of its schema."""


@dataclass(frozen=True, slots=True)
class StructuredPart[T: BaseModel]:
    """What a streamed structured call has written so far (ADR 0048)."""

    # The arguments parsed so far: the last value in them may still be cut off.
    args: dict[str, Any]
    # Last part only: `args` checked against the schema, or None when they don't fit
    # (the caller may still use the parts it can).
    output: T | None = None
    done: bool = False


async def astream_structured[T: BaseModel](
    ctx: TenantProviderContext,
    task: str,
    schema: type[T],
    messages: LanguageModelInput,
    *,
    config: RunnableConfig | None = None,
) -> AsyncIterator[StructuredPart[T]]:
    """Structured output for `task`, given as it is written (ADR 0048): one part each
    time the arguments grow, then a last part with the checked output.

    The schema is a forced tool call on every model, so its arguments stream as JSON.
    As with streamed text (get_llm), the next model takes over only if one fails before
    its first part; a failure after that raises. A model that answers in text instead
    raises StructuredOutputMissingError, so the next model answers.
    """
    models = get_chat_models(ctx, task)
    for i, model in enumerate(models):
        last = i == len(models) - 1
        started = False
        try:
            async for part in _stream_one(model, schema, messages, config):
                started = True
                yield part
            return
        except Exception:
            if started or last:
                raise
            logger.warning("%s: streamed structured call failed, next model", task, exc_info=True)


async def _stream_one[T: BaseModel](
    model: BaseChatModel,
    schema: type[T],
    messages: LanguageModelInput,
    config: RunnableConfig | None,
) -> AsyncIterator[StructuredPart[T]]:
    bound = model.bind_tools([schema], tool_choice=schema.__name__)
    message: AIMessageChunk | None = None
    written = 0
    async for chunk in bound.astream(messages, config=config):
        if not isinstance(chunk, AIMessageChunk):
            continue
        message = chunk if message is None else message + chunk
        size = sum(len(c.get("args") or "") for c in message.tool_call_chunks)
        if size > written and message.tool_calls:
            written = size
            yield StructuredPart(dict(message.tool_calls[0]["args"]))
    if message is None or not message.tool_calls:
        raise StructuredOutputMissingError(f"the model returned no {schema.__name__}")
    args = dict(message.tool_calls[0]["args"])
    try:
        output: T | None = schema.model_validate(args)
    except ValidationError:
        output = None
    yield StructuredPart(args, output, done=True)


def get_structured_llm[T: BaseModel](
    ctx: TenantProviderContext, task: str, schema: type[T]
) -> Runnable[LanguageModelInput, T]:
    """Structured-output model for `task`.

    Binds the schema to *each* model before chaining; relying on
    `RunnableWithFallbacks.__getattr__` forwarding is fragile (ADR 0002).
    """

    # langchain-core annotates the result as `dict | BaseModel` regardless of schema; with
    # a Pydantic schema it is an instance of `schema`, or None when the model answered in
    # text instead of calling the schema's tool (seen with qwen-plus as exercise critic).
    # None raises, so the next model in the chain answers, or the caller's error path runs.
    def require(output: Any) -> T:
        if not isinstance(output, schema):
            raise StructuredOutputMissingError(f"the model returned no {schema.__name__}")
        return output

    bound: list[Runnable[LanguageModelInput, T]] = [
        cast(
            Runnable[LanguageModelInput, Any],
            # ChatOpenAI defaults to OpenAI's `json_schema` response format, which most
            # OpenAI-compatible servers and relays reject; tool calling is near-universal.
            model.with_structured_output(schema, method="function_calling")
            if "kind:openai_compatible" in (model.tags or [])
            else model.with_structured_output(schema),
        )
        | RunnableLambda(require)
        for model in get_chat_models(ctx, task)
    ]
    return chain_with_fallbacks(bound)


def get_chat_model(ctx: TenantProviderContext, task: str) -> BaseChatModel:
    """Primary model only, without fallbacks, for BaseChatModel-specific APIs."""
    return get_chat_models(ctx, task)[0]


def reset_caches() -> None:
    get_providers_config.cache_clear()
    _models.clear()
