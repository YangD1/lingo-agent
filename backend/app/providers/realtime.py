"""Tenant-scoped realtime voice: the OpenAI Realtime protocol, or Gemini Live (ADR 0030 §2).

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

A `gemini` connection speaks Gemini Live (`BidiGenerateContent`, dialect "gemini"): the
model goes in its first message, not the address, and the key in the address's query
string (`?key=`), so every error that may quote the address goes through `redact_key`.
"""

import re
import uuid
from dataclasses import dataclass, replace
from typing import Any, Literal, cast
from urllib.parse import quote, urlsplit

from app.providers.config import REALTIME_KINDS, ResolvedModel, TenantProviderContext, resolve_route
from app.providers.errors import ProviderConfigError
from app.providers.llm import get_providers_config

type RealtimeDialect = Literal["ga", "beta", "gemini"]
# What a connection's `realtime_dialect` param may say (Gemini's comes from its kind).
DIALECTS: tuple[RealtimeDialect, ...] = ("ga", "beta")

_KEY_IN_QUERY = re.compile(r"([?&]key=)[^&#\s'\"]+")


def redact_key(text: str) -> str:
    """Mask a key sent in a query string (Gemini Live), so logs and errors never keep it."""
    return _KEY_IN_QUERY.sub(r"\1***", text)


@dataclass(frozen=True)
class _Vendor:
    dialect: RealtimeDialect
    input_rate: int
    output_rate: int
    # Where it listens when the connection doesn't say; None: next to base_url.
    url: str | None = None
    # None: the vendor's own default.
    voice: str | None = None
    # Model that transcribes the learner's speech for subtitles; None: not asked for.
    transcription: str | None = None
    # Beta spelling only: what `input_audio_format` / `output_audio_format` are called.
    formats: tuple[str, str] = ("pcm16", "pcm16")


# Checked 2026-10-10 (ADR 0030); PCM16 mono both ways. Voices,
# transcription models and Qwen's format names are from the docs, not yet from a real
# call: task 64's smoke test confirms them.
_OPENAI = _Vendor("ga", 24_000, 24_000, voice="marin", transcription="gpt-transcribe")
_QWEN_DETAILS: dict[str, Any] = {
    "transcription": "qwen3-asr-flash-realtime",
    "formats": ("pcm", "pcm"),
}
_QWEN = _Vendor(
    "beta", 16_000, 24_000, "wss://dashscope.aliyuncs.com/api-ws/v1/realtime", **_QWEN_DETAILS
)
_QWEN_INTL = _Vendor(
    "beta", 16_000, 24_000, "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime", **_QWEN_DETAILS
)
_STEPFUN = _Vendor(
    "beta", 24_000, 24_000, "wss://api.stepfun.com/v1/realtime", voice="qingchunshaonv"
)
# Checked 2026-10-11 (ai.google.dev/api/live): PCM16 16 kHz in, 24 kHz out; subtitles on
# both sides are switched on in the session's setup, with no model to name.
_GEMINI = _Vendor(
    "gemini",
    16_000,
    24_000,
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent",
)


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


type RealtimeVendor = Literal["openai", "qwen", "stepfun", "gemini"]


def realtime_vendor(model: ResolvedModel) -> RealtimeVendor | None:
    """Whose realtime API a model is, when known: for its voice catalog (ADR 0032 §3).
    None for other servers, even ones speaking a vendor's protocol."""
    if model.kind == "gemini":
        return "gemini"
    configured = model.params.get("realtime_url")
    host = (urlsplit(configured or model.base_url).hostname or "").lower()
    vendor = _vendor(host, model.kind)
    if vendor is _OPENAI:
        return "openai"
    if vendor in (_QWEN, _QWEN_INTL):
        return "qwen"
    if vendor is _STEPFUN:
        return "stepfun"
    return None


@dataclass(frozen=True)
class RealtimeTarget:
    """One model to connect to: where, in which spelling, at which sample rates."""

    model: ResolvedModel
    url: str  # with the model in the query, as every vendor takes it
    dialect: RealtimeDialect
    input_rate: int
    output_rate: int
    voice: str | None = None
    transcription: str | None = None
    formats: tuple[str, str] = ("pcm16", "pcm16")


def realtime_target(model: ResolvedModel) -> RealtimeTarget:
    configured = model.params.get("realtime_url")
    if model.kind == "gemini":
        return RealtimeTarget(
            model=model,
            url=configured or _GEMINI.url or "",
            dialect="gemini",
            input_rate=_GEMINI.input_rate,
            output_rate=_GEMINI.output_rate,
        )
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
        voice=vendor.voice,
        transcription=vendor.transcription,
        formats=vendor.formats,
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
    targets = [realtime_target(m) for m in resolved]
    tutor = ctx.tutor
    if tutor is not None and tutor.realtime_voice is not None:
        # The learner's voice, for the model it was picked for (ADR 0032 §3).
        targets = [
            replace(t, voice=tutor.realtime_voice)
            if f"{t.model.connection}:{t.model.model}" == tutor.realtime_model
            else t
            for t in targets
        ]
    return RealtimeRoute(ctx.tenant_id, tuple(targets))
