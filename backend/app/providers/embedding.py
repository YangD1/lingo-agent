"""Tenant-scoped embedding models. No fallback chain (ADR 0002 §2.5)."""

from typing import Any

from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings

from app.providers.cache import TTLCache
from app.providers.config import EMBEDDING_KINDS, TenantProviderContext, resolve_route
from app.providers.errors import ProviderConfigError
from app.providers.llm import get_providers_config
from app.providers.net_guard import make_async_http_client, make_blocked_sync_client
from app.settings import get_settings

_embeddings: TTLCache[tuple[object, ...], Embeddings] = TTLCache(maxsize=256, ttl_seconds=600)


def get_embeddings(ctx: TenantProviderContext, task: str = "default") -> Embeddings:
    (resolved,) = resolve_route(get_providers_config(), ctx, "embedding", task)
    if resolved.kind not in EMBEDDING_KINDS:
        raise ProviderConfigError(f"connection {resolved.connection!r} has no embeddings API")

    def build() -> Embeddings:
        params: dict[str, Any] = dict(resolved.params)
        kwargs: dict[str, Any] = {
            **params,
            "base_url": resolved.base_url,
            "http_async_client": make_async_http_client(
                allow_private=get_settings().provider_allow_private_networks,
                timeout=params.get("timeout"),
            ),
            "http_client": make_blocked_sync_client(),
        }
        if resolved.kind == "openai_compatible":
            # Non-OpenAI servers don't accept pre-tokenized input.
            kwargs["check_embedding_ctx_length"] = False
        if resolved.api_key is not None:
            kwargs["api_key"] = resolved.api_key.get_secret_value()
        return init_embeddings(resolved.model, provider="openai", **kwargs)

    return _embeddings.get_or_create((ctx.tenant_id, task, ctx.version), build)


def reset_caches() -> None:
    _embeddings.clear()
