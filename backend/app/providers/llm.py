"""Tenant-scoped, task-routed chat models with fallback chains (ADR 0002 + 0004).

Business code asks for a *task* in the context of a tenant, never a model name:

    ctx = await load_provider_context(session, tenant.id)
    reply = await get_llm(ctx, "chat").ainvoke(messages)
    parsed = await get_structured_llm(ctx, "memory_extract", MemorySchema).ainvoke(messages)
"""

from functools import lru_cache
from typing import Any, cast

from langchain.chat_models import init_chat_model
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from app.providers.cache import TTLCache
from app.providers.clients import GuardedChatAnthropic
from app.providers.config import (
    ProvidersConfig,
    ResolvedModel,
    TenantProviderContext,
    load_providers_config,
    resolve_route,
)
from app.providers.net_guard import make_async_http_client, make_blocked_sync_client
from app.settings import get_settings
from app.usage.recorder import UsageLabels, make_recorder

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


def build_chat_model(
    resolved: ResolvedModel,
    task: str,
    *,
    callbacks: list[BaseCallbackHandler] | None = None,
) -> BaseChatModel:
    params: dict[str, Any] = dict(resolved.params)
    http_client = make_async_http_client(
        allow_private=get_settings().provider_allow_private_networks,
        timeout=params.get("timeout"),
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

    # openai_compatible is just the OpenAI client pointed at another base_url.
    model_provider = "openai" if resolved.kind == "openai_compatible" else resolved.kind
    model = init_chat_model(
        resolved.model,
        model_provider=model_provider,
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
                        UsageLabels(ctx.tenant_id, task, r.connection, r.model, is_fallback=i > 0)
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


def get_structured_llm[T: BaseModel](
    ctx: TenantProviderContext, task: str, schema: type[T]
) -> Runnable[LanguageModelInput, T]:
    """Structured-output model for `task`.

    Binds the schema to *each* model before chaining; relying on
    `RunnableWithFallbacks.__getattr__` forwarding is fragile (ADR 0002).
    """
    # langchain-core annotates the result as `dict | BaseModel` regardless of schema;
    # with a Pydantic schema (and include_raw=False) it is always an instance of `schema`.
    bound = [
        cast(
            Runnable[LanguageModelInput, T],
            # ChatOpenAI defaults to OpenAI's `json_schema` response format, which most
            # OpenAI-compatible servers and relays reject; tool calling is near-universal.
            model.with_structured_output(schema, method="function_calling")
            if "kind:openai_compatible" in (model.tags or [])
            else model.with_structured_output(schema),
        )
        for model in get_chat_models(ctx, task)
    ]
    return chain_with_fallbacks(bound)


def get_chat_model(ctx: TenantProviderContext, task: str) -> BaseChatModel:
    """Primary model only, without fallbacks, for BaseChatModel-specific APIs."""
    return get_chat_models(ctx, task)[0]


def reset_caches() -> None:
    get_providers_config.cache_clear()
    _models.clear()
