"""Tenant-scoped text-to-speech: the server reads aloud (ADR 0018 §3, ADR 0028 §3).

Two kinds of endpoint:
- OpenAI's `POST /audio/speech` (OpenAI, SiliconFlow, a local speaches with Kokoro);
- Azure's text-to-speech REST API, SSML in, mp3 out (`azure_speech` connections).

    tts = get_tts(ctx)
    speech = await tts.synthesize("Nice to meet you.", language="en-US", speed=0.9)

Models in the route are tried in order; a model with no voice for the language is
skipped. Each attempt is written to llm_usage by characters, not tokens.
"""

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from xml.sax.saxutils import escape, quoteattr

from app.providers.config import (
    TTS_KINDS,
    ResolvedModel,
    TenantProviderContext,
    resolve_route,
    route_for,
)
from app.providers.errors import ProviderConfigError
from app.providers.llm import get_providers_config
from app.providers.net_guard import make_async_http_client
from app.settings import get_settings
from app.usage.recorder import UsageRecord, submit_usage

type Language = Literal["en-US", "en-GB", "zh-CN"]
LANGUAGES: tuple[Language, ...] = ("en-US", "en-GB", "zh-CN")

MIME_TYPE = "audio/mpeg"
AZURE_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
# Azure requires a User-Agent naming the application.
USER_AGENT = "lingo-agent"
DEFAULT_TIMEOUT = 20.0

# Voices when the route doesn't name one (ADR 0028 §3). Azure models are voices already;
# these cover the languages an Azure voice can't read.
AZURE_VOICES: Mapping[Language, str] = {
    "en-US": "en-US-AvaMultilingualNeural",
    "en-GB": "en-GB-SoniaNeural",
    "zh-CN": "zh-CN-XiaoxiaoMultilingualNeural",
}
# Kokoro v1.0's American, British and Mandarin voices (female, so a reply that switches
# language keeps one gender, as in ADR 0018 §1).
KOKORO_VOICES: Mapping[Language, str] = {
    "en-US": "af_heart",
    "en-GB": "bf_emma",
    "zh-CN": "zf_xiaoxiao",
}
# OpenAI's voices read every language; so do CosyVoice's, named "<model>:<voice>".
OPENAI_VOICE = "coral"
COSYVOICE_VOICE = "anna"


@dataclass(frozen=True)
class Speech:
    audio: bytes
    connection: str
    model: str
    voice: str
    mime_type: str = MIME_TYPE


class SpeechSynthesisError(Exception):
    """Every model in the route failed (or none has a voice for the language); the last
    error is chained."""


class EndpointError(Exception):
    """The vendor answered with an error status; the message is safe to log."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"HTTP {status}: {message}")


def default_voice(model: ResolvedModel, language: Language) -> str | None:
    """The built-in voice `model` reads `language` with, or None when it has none."""
    name = model.model
    if model.kind == "azure_speech":
        locale = "-".join(name.split("-")[:2])
        if locale == language:
            return name
        # A multilingual voice reads other languages, but not another accent of its own:
        # a British learner gets a British voice.
        if "Multilingual" in name and locale.split("-")[0] != language.split("-")[0]:
            return name
        return AZURE_VOICES[language]
    lowered = name.lower()
    if "kokoro" in lowered:
        return KOKORO_VOICES[language]
    if "cosyvoice" in lowered:
        return f"{name}:{COSYVOICE_VOICE}"
    if model.kind == "openai" or "tts" in lowered:
        return OPENAI_VOICE
    return None


def azure_rate(speed: float) -> str:
    """SSML prosody rate for a speed factor: 0.9 -> "-10%"."""
    return f"{round((speed - 1) * 100):+d}%"


def azure_ssml(text: str, language: Language, voice: str, speed: float) -> str:
    return (
        f"<speak version='1.0' xml:lang={quoteattr(language)}>"
        f"<voice xml:lang={quoteattr(language)} name={quoteattr(voice)}>"
        f"<prosody rate={quoteattr(azure_rate(speed))}>{escape(text)}</prosody>"
        "</voice></speak>"
    )


@dataclass(frozen=True)
class TextToSpeech:
    tenant_id: uuid.UUID
    models: tuple[ResolvedModel, ...]
    # Route overrides: "<connection>:<model>" -> language -> voice.
    voices: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    task: str = "tts"  # llm_usage label; connection tests use their own

    def voice_for(self, model: ResolvedModel, language: Language) -> str | None:
        override = self.voices.get(f"{model.connection}:{model.model}", {}).get(language)
        return override or default_voice(model, language)

    def candidates(self, language: Language) -> list[tuple[ResolvedModel, str]]:
        """The models that can read `language`, in route order, with their voices."""
        return [(m, v) for m in self.models if (v := self.voice_for(m, language)) is not None]

    async def synthesize(
        self,
        text: str,
        *,
        language: Language,
        speed: float = 1.0,
        user_id: uuid.UUID | None = None,
        background: bool = False,
    ) -> Speech:
        last_error: Exception | None = None
        for i, (model, voice) in enumerate(self.candidates(language)):
            started = time.monotonic()
            try:
                audio = await _synthesize(model, text, language, voice, speed)
            except Exception as exc:
                last_error = exc
                self._record(model, i, started, text, user_id, background, error=exc)
                continue
            self._record(model, i, started, text, user_id, background)
            return Speech(audio=audio, connection=model.connection, model=model.model, voice=voice)
        raise SpeechSynthesisError(f"no text-to-speech model could read {language}") from last_error

    def _record(
        self,
        model: ResolvedModel,
        position: int,
        started: float,
        text: str,
        user_id: uuid.UUID | None,
        background: bool,
        *,
        error: Exception | None = None,
    ) -> None:
        submit_usage(
            UsageRecord(
                tenant_id=self.tenant_id,
                user_id=user_id,
                conversation_id=None,
                task=self.task,
                connection_name=model.connection,
                model=model.model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="error" if error is not None else "ok",
                is_fallback=position > 0,
                # The class name only: messages can echo request details.
                error_code=type(error).__name__[:64] if error is not None else None,
                # Vendors bill a failed request too when it reached them; count what was sent.
                characters=len(text),
                background=background,
            )
        )


async def _synthesize(
    model: ResolvedModel, text: str, language: Language, voice: str, speed: float
) -> bytes:
    key = model.api_key.get_secret_value() if model.api_key else None
    if model.kind == "azure_speech":
        url = f"{model.base_url}/cognitiveservices/v1"
        headers = {
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": AZURE_OUTPUT_FORMAT,
            "User-Agent": USER_AGENT,
        }
        if key:
            headers["Ocp-Apim-Subscription-Key"] = key
        body: dict[str, object] | str = azure_ssml(text, language, voice, speed)
    else:
        url = f"{model.base_url}/audio/speech"
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        body = {
            "model": model.model,
            "input": text,
            "voice": voice,
            "speed": min(max(speed, 0.25), 4.0),
            "response_format": "mp3",
        }
    timeout = float(model.params.get("timeout") or DEFAULT_TIMEOUT)
    async with make_async_http_client(
        allow_private=get_settings().provider_allow_private_networks, timeout=timeout
    ) as client:
        if isinstance(body, str):
            response = await client.post(url, headers=headers, content=body.encode())
        else:
            response = await client.post(url, headers=headers, json=body)
    if response.status_code != 200:
        raise EndpointError(response.status_code, response.text.strip()[:200])
    if not response.content:
        raise EndpointError(response.status_code, "empty audio")
    return response.content


def get_tts(ctx: TenantProviderContext) -> TextToSpeech:
    """Raises NoModelConfiguredError (code `no_tts_model`) when nothing is configured."""
    config = get_providers_config()
    resolved = resolve_route(config, ctx, "tts", "default")
    for model in resolved:
        if model.kind not in TTS_KINDS:  # routes are validated on save; YAML at startup
            raise ProviderConfigError(f"connection {model.connection!r} cannot read text aloud")
    # Voice overrides are the route's own params (ADR 0028 §3).
    voices = route_for(config, ctx, "tts", "default").params.get("voices") or {}
    return TextToSpeech(ctx.tenant_id, tuple(resolved), voices)
