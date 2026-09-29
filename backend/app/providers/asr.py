"""Tenant-scoped speech-to-text over OpenAI's /audio/transcriptions (ADR 0008 §5).

The same endpoint is served by OpenAI, Groq, SiliconFlow and a local speaches
container, so one client covers prod APIs and dev's local model alike:

    ctx = await load_provider_context(session, tenant.id)
    transcript = await get_asr(ctx).transcribe(audio, filename="rec.webm", mime_type=...)

Models in the route are tried in order; each attempt is written to llm_usage.
"""

import io
import time
import uuid
import wave
from dataclasses import dataclass
from functools import cache

from openai import AsyncOpenAI
from openai.types.audio import Transcription, TranscriptionDiarized, TranscriptionVerbose

from app.providers.config import ASR_KINDS, ResolvedModel, TenantProviderContext, resolve_route
from app.providers.errors import ProviderConfigError
from app.providers.llm import get_providers_config
from app.providers.net_guard import make_async_http_client
from app.settings import get_settings
from app.usage.recorder import UsageRecord, submit_usage

_KEYLESS_PLACEHOLDER = "not-needed"

# What the SDK's create() is typed to return; with response_format="json" servers send
# the plain shape, but some (speaches, Groq) add verbose fields such as `duration`.
type AnyTranscription = Transcription | TranscriptionVerbose | TranscriptionDiarized


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None
    duration_seconds: float | None = None


class TranscriptionError(Exception):
    """Every model in the route failed; the last error is chained."""


@dataclass(frozen=True)
class SpeechToText:
    tenant_id: uuid.UUID
    models: tuple[ResolvedModel, ...]
    task: str = "asr"  # llm_usage label; connection tests use their own

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        mime_type: str,
        user_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
    ) -> Transcript:
        last_error: Exception | None = None
        for i, model in enumerate(self.models):
            started = time.monotonic()
            try:
                # Short-lived client: transcriptions are rare, and closing it releases
                # the guarded connection pool with it.
                async with _client(model) as client:
                    result = await client.audio.transcriptions.create(
                        file=(filename, audio, mime_type),
                        model=model.model,
                        # Plain `json` is what every server supports; `verbose_json` is
                        # whisper-only and OpenAI's gpt-transcribe rejects it.
                        response_format="json",
                    )
            except Exception as exc:
                last_error = exc
                self._record(model, i, started, user_id, conversation_id, error=exc)
                continue
            transcript = _transcript(result)
            self._record(
                model, i, started, user_id, conversation_id, result=result, transcript=transcript
            )
            return transcript
        raise TranscriptionError("every speech-to-text model failed") from last_error

    def _record(
        self,
        model: ResolvedModel,
        position: int,
        started: float,
        user_id: uuid.UUID | None,
        conversation_id: uuid.UUID | None,
        *,
        result: AnyTranscription | None = None,
        transcript: Transcript | None = None,
        error: Exception | None = None,
    ) -> None:
        usage = getattr(result, "usage", None)
        tokens = (
            (usage.input_tokens, usage.output_tokens)
            if usage is not None and usage.type == "tokens"
            else (0, 0)
        )
        submit_usage(
            UsageRecord(
                tenant_id=self.tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                task=self.task,
                connection_name=model.connection,
                model=model.model,
                input_tokens=tokens[0],
                output_tokens=tokens[1],
                latency_ms=int((time.monotonic() - started) * 1000),
                status="error" if error is not None else "ok",
                is_fallback=position > 0,
                # The class name only: messages can echo request details.
                error_code=type(error).__name__[:64] if error is not None else None,
                audio_seconds=transcript.duration_seconds if transcript is not None else None,
            )
        )


def _client(model: ResolvedModel) -> AsyncOpenAI:
    params = model.params
    api_key = model.api_key.get_secret_value() if model.api_key else _KEYLESS_PLACEHOLDER
    return AsyncOpenAI(
        api_key=api_key,
        base_url=model.base_url,
        max_retries=int(params.get("max_retries", 1)),
        http_client=make_async_http_client(
            allow_private=get_settings().provider_allow_private_networks,
            timeout=params.get("timeout"),
        ),
    )


def _transcript(result: AnyTranscription) -> Transcript:
    usage = getattr(result, "usage", None)
    duration = usage.seconds if usage is not None and usage.type == "duration" else None
    if duration is None:
        value = getattr(result, "duration", None) or (result.model_extra or {}).get("duration")
        duration = float(value) if isinstance(value, int | float) else None
    languages = getattr(result, "languages", None) or []
    language = languages[0].code if languages else getattr(result, "language", None)
    return Transcript(
        text=result.text.strip(),
        language=language if isinstance(language, str) else None,
        duration_seconds=duration,
    )


@cache
def silent_clip() -> bytes:
    """Half a second of 16 kHz mono silence as WAV, for testing a connection.

    Only whether the server accepts a transcription request matters, not the text
    (whisper may even invent some for silence).
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(16_000)
        clip.writeframes(b"\x00\x00" * 8_000)
    return buffer.getvalue()


def get_asr(ctx: TenantProviderContext) -> SpeechToText:
    """Raises NoModelConfiguredError (code `no_asr_model`) when nothing is configured."""
    resolved = resolve_route(get_providers_config(), ctx, "asr", "default")
    for model in resolved:
        if model.kind not in ASR_KINDS:  # routes are validated on save; YAML at startup
            raise ProviderConfigError(f"connection {model.connection!r} has no speech-to-text API")
    return SpeechToText(ctx.tenant_id, tuple(resolved))
