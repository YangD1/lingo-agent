"""Shared builders for provider-layer tests."""

import uuid
from typing import Any

from pydantic import SecretStr

from app.providers.config import (
    ConnectionSpec,
    ProviderKind,
    ProvidersConfig,
    RouteSpec,
    TenantProviderContext,
)

TENANT = uuid.UUID("00000000-0000-0000-0000-00000000000a")


def make_config(**overrides: Any) -> ProvidersConfig:
    raw: dict[str, Any] = {
        "presets": {
            "deepseek": {"kind": "deepseek", "base_url": "https://api.deepseek.com/v1"},
            "anthropic": {"kind": "anthropic", "base_url": "https://api.anthropic.com"},
            "openai": {"kind": "openai", "base_url": "https://api.openai.com/v1"},
        },
        "defaults": {"timeout": 30, "max_retries": 1},
        "llm": {
            "default": ["deepseek:deepseek-chat", "openai:gpt-5-mini"],
            "routes": {"chat": {"models": ["openai:gpt-5-mini"], "temperature": 0.7}},
        },
        "embedding": {"default": "openai:text-embedding-3-small"},
    }
    raw.update(overrides)
    return ProvidersConfig.model_validate(raw)


def conn(
    name: str,
    kind: ProviderKind | None = None,
    *,
    base_url: str | None = None,
    key: str | None = "sk-test",
    **params: Any,
) -> ConnectionSpec:
    kind = kind or name  # type: ignore[assignment]
    return ConnectionSpec(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        base_url=base_url or f"https://{name}.example.com/v1",
        api_key=SecretStr(key) if key is not None else None,
        params=params,
    )


def make_ctx(
    *connections: ConnectionSpec,
    routes: dict[tuple[str, str], RouteSpec] | None = None,
    version: str = "v1",
) -> TenantProviderContext:
    return TenantProviderContext(
        tenant_id=TENANT,
        connections={c.name: c for c in connections},
        routes=routes or {},
        version=version,
    )
