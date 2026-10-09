"""Tenant provider connections and route overrides (ADR 0004 §6)."""

import base64
import re
import struct
import time
import uuid
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from typing import Annotated, Any, Literal

import openai
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.crypto import Keyring, connection_aad
from app.db.models import PROVIDER_KINDS, ProviderConnection, TenantModelRoute
from app.providers.asr import SpeechToText, TranscriptionError, silent_clip
from app.providers.cache import TTLCache
from app.providers.config import (
    SPEECH_ONLY_KINDS,
    ProviderKind,
    ProvidersConfig,
    ResolvedModel,
    RouteSpec,
    Section,
    check_asr_route,
    check_embedding_route,
    check_llm_route,
    check_tts_route,
)
from app.providers.errors import ProviderConfigError
from app.providers.llm import build_chat_model
from app.providers.model_catalog import DiscoveredModel, categorize, fetch_models
from app.providers.net_guard import make_async_http_client, validate_base_url
from app.providers.tts import (
    LANGUAGES,
    EndpointError,
    Language,
    SpeechSynthesisError,
    TextToSpeech,
    default_voice,
)
from app.settings import get_settings
from app.usage.recorder import UsageLabels, make_recorder

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Kinds whose official APIs always need a key; openai_compatible may be keyless (Ollama).
_KEY_REQUIRED: frozenset[str] = frozenset({"deepseek", "anthropic", "openai", "azure_speech"})


type TestPurpose = Literal["chat", "asr", "vision", "tts"]
type VoiceName = Annotated[str, Field(min_length=1, max_length=128)]


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class CallParams(BaseModel):
    """Allow-list of model call parameters a tenant may set.

    These are passed straight into the SDK client constructors, so anything else
    (http_async_client, default_headers, openai_proxy, ...) could bypass the SSRF guard
    or leak data. `extra="forbid"` is the security boundary here.
    """

    model_config = ConfigDict(extra="forbid")

    timeout: Annotated[float, Field(gt=0, le=600)] | None = None
    max_retries: Annotated[int, Field(ge=0, le=5)] | None = None
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    max_tokens: Annotated[int, Field(gt=0, le=200_000)] | None = None
    top_p: Annotated[float, Field(gt=0, le=1)] | None = None
    # On by default so streamed calls report token usage; off for servers that reject it.
    stream_usage: bool | None = None
    # tts routes only (ADR 0028 §3): the voice each model reads a language with, keyed by
    # "<connection>:<model>", over the built-in voices. Never sent to a chat SDK.
    voices: dict[Annotated[str, Field(max_length=200)], dict[Language, VoiceName]] | None = (
        None
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


def key_hint(api_key: str) -> str:
    return f"…{api_key[-4:]}" if len(api_key) >= 12 else "…"


def _check_connection_params(params: CallParams) -> None:
    # Connection params reach every SDK the connection is used with.
    if params.voices is not None:
        raise ProviderConfigError("voices belong on a text-to-speech route, not a connection")


def _check_name(name: str) -> str:
    if not _NAME.match(name):
        raise ProviderConfigError(
            "connection name must be 1-64 chars of lowercase letters, digits, '_' or '-'"
        )
    return name


async def list_connections(session: AsyncSession, tenant_id: uuid.UUID) -> list[ProviderConnection]:
    rows = await session.scalars(
        select(ProviderConnection)
        .where(ProviderConnection.tenant_id == tenant_id)
        .order_by(ProviderConnection.created_at)
    )
    return list(rows)


async def get_connection(
    session: AsyncSession, tenant_id: uuid.UUID, connection_id: uuid.UUID
) -> ProviderConnection:
    conn = await session.get(ProviderConnection, connection_id)
    # Same 404 for "missing" and "belongs to another tenant": don't leak existence.
    if conn is None or conn.tenant_id != tenant_id:
        raise NotFoundError("connection not found")
    return conn


async def create_connection(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    config: ProvidersConfig,
    keyring: Keyring,
    allow_private: bool,
    preset: str | None,
    name: str | None,
    kind: str | None,
    base_url: str | None,
    api_key: SecretStr | None,
    params: CallParams,
    default_model: str | None = None,
) -> ProviderConnection:
    default_model = _clean_model(default_model)
    if preset is not None:
        spec = config.presets.get(preset)
        if spec is None:
            raise ProviderConfigError(f"unknown preset {preset!r}")
        kind = kind or spec.kind
        base_url = base_url or spec.base_url
        name = name or preset
        # The preset's recommended chat model; speech-only vendors have none (ADR 0028).
        if default_model is None and kind not in SPEECH_ONLY_KINDS:
            default_model = next((m for m in spec.models if categorize(m) == "chat"), None)
    if kind not in PROVIDER_KINDS:
        raise ProviderConfigError(f"kind must be one of {', '.join(PROVIDER_KINDS)}")
    _check_connection_params(params)
    if not name or not base_url:
        raise ProviderConfigError("name and base_url are required when no preset is given")
    if kind in _KEY_REQUIRED and api_key is None:
        raise ProviderConfigError(f"{kind} connections need an API key")

    conn = ProviderConnection(
        id=uuid.uuid4(),  # assigned up front: the ciphertext's AAD includes it
        tenant_id=tenant_id,
        name=_check_name(name),
        kind=kind,
        base_url=await validate_base_url(base_url, allow_private=allow_private),
        params=params.to_dict(),
        default_model=default_model,
    )
    _set_api_key(conn, api_key, keyring)
    session.add(conn)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(f"a connection named {name!r} already exists") from exc
    return conn


async def update_connection(
    session: AsyncSession,
    conn: ProviderConnection,
    *,
    keyring: Keyring,
    allow_private: bool,
    base_url: str | None = None,
    api_key: SecretStr | None = None,
    clear_api_key: bool = False,
    params: CallParams | None = None,
    enabled: bool | None = None,
    default_model: str | None = None,
    name: str | None = None,
    kind: str | None = None,
) -> ProviderConnection:
    """Partial update of any field (ADR 0007 §4).

    Renaming rewrites the tenant's route overrides that reference the old name, in the same
    transaction. `default_model=""` clears the default model; None leaves it unchanged."""
    endpoint_changed = False
    if kind is not None and kind != conn.kind:
        if kind not in PROVIDER_KINDS:
            raise ProviderConfigError(f"kind must be one of {', '.join(PROVIDER_KINDS)}")
        conn.kind = kind
        endpoint_changed = True
    if base_url is not None:
        conn.base_url = await validate_base_url(base_url, allow_private=allow_private)
        endpoint_changed = True
    if clear_api_key:
        if conn.kind in _KEY_REQUIRED:
            raise ProviderConfigError(f"{conn.kind} connections need an API key")
        _set_api_key(conn, None, keyring)
        endpoint_changed = True
    elif api_key is not None:
        _set_api_key(conn, api_key, keyring)
        endpoint_changed = True
    if params is not None:
        _check_connection_params(params)
        conn.params = params.to_dict()
    if enabled is not None:
        conn.enabled = enabled
    if default_model is not None:
        conn.default_model = _clean_model(default_model)
    # Checked after both kind and key may have changed, so switching to a key-requiring
    # kind and supplying its key can happen in one request.
    if conn.kind in _KEY_REQUIRED and conn.encrypted_api_key is None:
        raise ProviderConfigError(f"{conn.kind} connections need an API key")
    if name is not None and name != conn.name:
        await _rename(session, conn, _check_name(name))
        endpoint_changed = True
    if endpoint_changed:  # the previous test result no longer applies
        conn.last_verified_at = None
        conn.last_error = None
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(f"a connection named {name!r} already exists") from exc
    return conn


async def _rename(session: AsyncSession, conn: ProviderConnection, new_name: str) -> None:
    """Point the tenant's route overrides at the new name. Usage history keeps the old one:
    it records what was called at the time."""
    old_prefix, new_prefix = f"{conn.name}:", f"{new_name}:"
    routes = await session.scalars(
        select(TenantModelRoute).where(TenantModelRoute.tenant_id == conn.tenant_id)
    )

    def renamed(refs: list[str]) -> list[str]:
        # A new list, so SQLAlchemy sees the JSONB column change.
        return [
            new_prefix + ref[len(old_prefix) :] if ref.startswith(old_prefix) else ref
            for ref in refs
        ]

    for route in routes:
        if any(ref.startswith(old_prefix) for ref in route.models):
            route.models = renamed(route.models)
            # Switched-off refs must keep matching their entries in `models`.
            route.disabled = renamed(route.disabled)
    conn.name = new_name


async def delete_connection(session: AsyncSession, conn: ProviderConnection) -> None:
    await session.delete(conn)
    await session.commit()


def _set_api_key(conn: ProviderConnection, api_key: SecretStr | None, keyring: Keyring) -> None:
    if api_key is None:
        conn.encrypted_api_key = None
        conn.key_hint = None
        return
    secret = api_key.get_secret_value()
    conn.encrypted_api_key = keyring.encrypt(secret, connection_aad(conn.tenant_id, conn.id))
    conn.key_hint = key_hint(secret)


@dataclass(frozen=True)
class TestResult:
    ok: bool
    error: str | None
    # Set when the failure has a cause the UI explains itself.
    error_code: str | None
    latency_ms: int


async def verify_connection(
    session: AsyncSession,
    conn: ProviderConnection,
    *,
    keyring: Keyring,
    model: str,
    purpose: TestPurpose = "chat",
) -> TestResult:
    """Send one tiny request through the same guarded client real calls use: a chat
    message, for speech-to-text a short built-in clip, for vision a small built-in image,
    for text-to-speech one word read aloud."""
    api_key = _decrypt_key(conn, keyring)
    kind: ProviderKind = conn.kind  # type: ignore[assignment]  # DB CHECK constraint
    resolved = ResolvedModel(
        connection=conn.name,
        kind=kind,
        model=model,
        base_url=conn.base_url,
        api_key=api_key,
        params={
            **conn.params,
            "max_retries": 0,
            "timeout": min(conn.params.get("timeout", 20), 20),
        },
    )
    started = time.monotonic()
    error: str | None = None
    error_code: str | None = None
    # The test hits the tenant's real account, so it shows up in their usage too.
    try:
        if purpose == "asr":
            stt = SpeechToText(conn.tenant_id, (resolved,), task="connection_test")
            await stt.transcribe(silent_clip(), filename="test.wav", mime_type="audio/wav")
        elif purpose == "tts":
            tts = TextToSpeech(conn.tenant_id, (resolved,), task="connection_test")
            # An Azure voice is tested in its own language; the rest read English.
            language: Language = next((x for x in LANGUAGES if model.startswith(x)), "en-US")
            if default_voice(resolved, language) is None:
                raise ProviderConfigError("no built-in voice for this model; set one on the route")
            await tts.synthesize("Hello", language=language)
        else:
            recorder = make_recorder(
                UsageLabels(conn.tenant_id, "connection_test", conn.name, model)
            )
            await build_chat_model(resolved, task="connection_test", callbacks=[recorder]).ainvoke(
                [
                    _vision_probe()
                    if purpose == "vision"
                    else HumanMessage("Reply with the single word OK.")
                ]
            )
    except Exception as exc:  # any vendor/network failure is a test result, not a 500
        wrapped = isinstance(exc, TranscriptionError | SpeechSynthesisError)
        cause = exc.__cause__ if wrapped and exc.__cause__ else exc
        error = f"{type(cause).__name__}: {cause}"[:500]
        # A server without /audio/transcriptions (a chat-only relay) answers 404.
        if purpose == "asr" and isinstance(cause, openai.NotFoundError):
            error_code = "asr_not_supported"
        # Likewise a server without /audio/speech.
        elif purpose == "tts" and isinstance(cause, EndpointError) and cause.status == 404:
            error_code = "tts_not_supported"
        # Models without image input are refused with a 400 by OpenAI-style servers.
        elif purpose == "vision" and isinstance(cause, openai.BadRequestError):
            error_code = "vision_not_supported"
    latency_ms = int((time.monotonic() - started) * 1000)

    if error is None:
        conn.last_verified_at = datetime.now(UTC)
    conn.last_error = error
    await session.commit()
    return TestResult(error is None, error, error_code, latency_ms)


def _vision_probe() -> HumanMessage:
    return HumanMessage(
        content=[
            {"type": "text", "text": "What colour is this image? Reply with one word."},
            {
                "type": "image",
                "base64": base64.b64encode(test_image()).decode("ascii"),
                "mime_type": "image/png",
            },
        ]
    )


@cache
def test_image() -> bytes:
    """A 32x32 red square as PNG, for testing a connection's vision. Some servers
    refuse images smaller than about 28 pixels a side."""
    size = 32

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _clean_model(model: str | None) -> str | None:
    return (model or "").strip() or None


def _decrypt_key(conn: ProviderConnection, keyring: Keyring) -> SecretStr | None:
    if conn.encrypted_api_key is None:
        return None
    return SecretStr(
        keyring.decrypt(conn.encrypted_api_key, connection_aad(conn.tenant_id, conn.id))
    )


# Model lists change rarely; updated_at in the key refetches after a key or URL change.
_MODELS_CACHE: TTLCache[tuple[uuid.UUID, datetime], list[DiscoveredModel]] = TTLCache(
    maxsize=256, ttl_seconds=600
)
MODEL_LIST_TIMEOUT_SECONDS = 15.0


async def list_connection_models(
    conn: ProviderConnection, *, keyring: Keyring
) -> list[DiscoveredModel]:
    """The connection's models from the vendor (ADR 0007 §1). Raises ModelListError."""
    cache_key = (conn.id, conn.updated_at)
    cached = _MODELS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    kind: ProviderKind = conn.kind  # type: ignore[assignment]  # DB CHECK constraint
    async with make_async_http_client(
        allow_private=get_settings().provider_allow_private_networks,
        timeout=MODEL_LIST_TIMEOUT_SECONDS,
    ) as client:
        models = await fetch_models(kind, conn.base_url, _decrypt_key(conn, keyring), client=client)
    _MODELS_CACHE.put(cache_key, models)
    return models


def reset_model_cache() -> None:
    _MODELS_CACHE.clear()


# --- routes -------------------------------------------------------------------------------


def known_tasks(config: ProvidersConfig, section: Section) -> list[str]:
    spec = config.section(section)
    return [] if spec is None else list(spec.all_routes())


async def list_route_overrides(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[TenantModelRoute]:
    rows = await session.scalars(
        select(TenantModelRoute).where(TenantModelRoute.tenant_id == tenant_id)
    )
    return list(rows)


async def put_route(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    config: ProvidersConfig,
    section: Section,
    task: str,
    models: list[str],
    params: CallParams,
    disabled: list[str] | None = None,
) -> TenantModelRoute:
    if task not in known_tasks(config, section):
        raise ProviderConfigError(f"unknown {section} task {task!r}")
    try:
        route = RouteSpec(models=models, params=params.to_dict(), disabled=disabled or [])
    except ValueError as exc:
        raise ProviderConfigError(str(exc)) from exc
    connections = {c.name: c for c in await list_connections(session, tenant_id)}
    for ref in route.models:
        if ref.partition(":")[0] not in connections:
            raise ProviderConfigError(f"no connection named {ref.partition(':')[0]!r}")
    if route.params.get("voices") is not None:
        if section != "tts":
            raise ProviderConfigError("voices can only be set on a text-to-speech route")
        for ref in route.params["voices"]:
            if ref not in route.models:
                raise ProviderConfigError(f"voices for {ref!r}, which is not in the route")
    checks = {
        "llm": check_llm_route,
        "embedding": check_embedding_route,
        "asr": check_asr_route,
        "tts": check_tts_route,
    }
    if section in checks:
        try:
            checks[section](route, lambda n: connections[n].kind)
        except ValueError as exc:
            raise ProviderConfigError(str(exc)) from exc

    existing = await session.scalar(
        select(TenantModelRoute).where(
            TenantModelRoute.tenant_id == tenant_id,
            TenantModelRoute.section == section,
            TenantModelRoute.task == task,
        )
    )
    if existing is None:
        existing = TenantModelRoute(tenant_id=tenant_id, section=section, task=task)
        session.add(existing)
    existing.models = route.models
    existing.params = route.params
    existing.disabled = route.disabled
    await session.commit()
    return existing


async def delete_route(
    session: AsyncSession, *, tenant_id: uuid.UUID, section: Section, task: str
) -> None:
    """Revert a task to the deployment's default route."""
    existing = await session.scalar(
        select(TenantModelRoute).where(
            TenantModelRoute.tenant_id == tenant_id,
            TenantModelRoute.section == section,
            TenantModelRoute.task == task,
        )
    )
    if existing is None:
        raise NotFoundError("no override for this task")
    await session.delete(existing)
    await session.commit()
