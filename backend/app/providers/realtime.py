"""Tenant-scoped realtime voice over the OpenAI Realtime protocol (ADR 0030 §2).

OpenAI, Qwen-Omni and StepFun all speak it over a WebSocket, in two spellings: OpenAI's
current one ("ga": `session.type`, nested `audio.input/output`, `response.output_audio.*`)
and the older beta one Qwen and StepFun keep (flat `input_audio_format`,
`response.audio.*`). Where each vendor listens, which spelling it speaks and the sample
rates it wants are told from the connection's address (Q60c); a connection can name them
with the `realtime_url` / `realtime_dialect` params instead.

    ctx = await load_provider_context(session, tenant.id)
    for target in get_realtime(ctx).targets:  # tried in order when connecting only
        ...

The backend relays audio without decoding it (ADR 0030 §1): the browser records and
plays at the rates given here.
"""

import uuid
from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import quote, urlsplit

from app.providers.config import REALTIME_KINDS, ResolvedModel, TenantProviderContext, resolve_route
from app.providers.errors import ProviderConfigError
from app.providers.llm import get_providers_config

type RealtimeDialect = Literal["ga", "beta"]
DIALECTS: tuple[RealtimeDialect, ...] = ("ga", "beta")


@dataclass(frozen=True)
class _Vendor:
    dialect: RealtimeDialect
    input_rate: int
    output_rate: int
    # Where it listens when the connection doesn't say; None: next to base_url.
    url: str | None = None


# Checked 2026-10-10 (docs/plans/P3-voice.md §2.1). PCM16 mono both ways.
_OPENAI = _Vendor("ga", 24_000, 24_000)
_QWEN = _Vendor("beta", 16_000, 24_000, "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
_QWEN_INTL = _Vendor("beta", 16_000, 24_000, "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime")
_STEPFUN = _Vendor("beta", 24_000, 24_000, "wss://api.stepfun.com/v1/realtime")


def _vendor(host: str, kind: str) -> _Vendor:
    if host == "api.openai.com":
        return _OPENAI
    if host == "dashscope-intl.aliyuncs.com":
        return _QWEN_INTL
    # dashscope.aliyuncs.com, or a workspace's own {id}.{region}.maas.aliyuncs.com (3.8).
    if host == "dashscope.aliyuncs.com" or host.endswith(".maas.aliyuncs.com"):
        return _QWEN
    if host == "api.stepfun.com":
        return _STEPFUN
    # Unknown servers: an OpenAI connection speaks OpenAI's current spelling; anything
    # else claiming compatibility most likely copied the older one.
    return _Vendor("ga" if kind == "openai" else "beta", 24_000, 24_000)


@dataclass(frozen=True)
class RealtimeTarget:
    """One model to connect to: where, in which spelling, at which sample rates."""

    model: ResolvedModel
    url: str  # with the model in the query, as every vendor takes it
    dialect: RealtimeDialect
    input_rate: int
    output_rate: int


def realtime_target(model: ResolvedModel) -> RealtimeTarget:
    configured = model.params.get("realtime_url")
    host = urlsplit(configured or model.base_url).hostname or ""
    vendor = _vendor(host.lower(), model.kind)
    base = configured or vendor.url or _next_to(model.base_url)
    dialect = model.params.get("realtime_dialect") or vendor.dialect
    if dialect not in DIALECTS:  # params are validated on save; YAML has none
        raise ProviderConfigError(f"unknown realtime_dialect {dialect!r}")
    return RealtimeTarget(
        model=model,
        url=f"{base}?model={quote(model.model, safe='')}",
        dialect=cast(RealtimeDialect, dialect),
        input_rate=vendor.input_rate,
        output_rate=vendor.output_rate,
    )


def _next_to(base_url: str) -> str:
    # https://api.example.com/v1 -> wss://api.example.com/v1/realtime
    return "ws" + base_url.rstrip("/").removeprefix("http") + "/realtime"


@dataclass(frozen=True)
class RealtimeRoute:
    tenant_id: uuid.UUID
    # In route order: the next one is tried only when connecting fails (ADR 0030 §2).
    targets: tuple[RealtimeTarget, ...]


def get_realtime(ctx: TenantProviderContext) -> RealtimeRoute:
    """Raises NoModelConfiguredError (code `no_realtime_model`) when nothing is configured."""
    resolved = resolve_route(get_providers_config(), ctx, "realtime", "default")
    for model in resolved:
        if model.kind not in REALTIME_KINDS:  # routes are validated on save; YAML at startup
            raise ProviderConfigError(f"connection {model.connection!r} has no realtime voice API")
    return RealtimeRoute(ctx.tenant_id, tuple(realtime_target(m) for m in resolved))
