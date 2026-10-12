"""Tenant-scoped text-to-speech: the server reads aloud (ADR 0018 §3, ADR 0028 §3).

Three kinds of endpoint:
- OpenAI's `POST /audio/speech` (OpenAI, SiliconFlow, a local speaches with Kokoro);
- Azure's text-to-speech REST API, SSML in, mp3 out (`azure_speech` connections);
- Alibaba Bailian's qwen-audio speech synthesis: the voice is described in a prompt, and
  the answer is a link to the audio, fetched in a second request (task 64.2a).

    tts = get_tts(ctx)
    speech = await tts.synthesize("Nice to meet you.", language="en-US", speed=0.9)

Models in the route are tried in order; a model with no voice for the language is
skipped. Each attempt is written to llm_usage by characters, not tokens.
"""

import asyncio
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from xml.sax.saxutils import escape, quoteattr

import httpx2

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
# Kokoro v1.0's American and British voices (female, like the others, so a reply that
# switches language keeps one gender, ADR 0018 §1). No Mandarin: speaches 0.9 phonemizes
# with espeak, which has no "zh", and answers 200 with no audio (measured, task 53.4).
KOKORO_VOICES: Mapping[Language, str] = {
    "en-US": "af_heart",
    "en-GB": "bf_emma",
}
# OpenAI's voices read every language; so do CosyVoice's, named "<model>:<voice>".
OPENAI_VOICE = "coral"
COSYVOICE_VOICE = "anna"
# qwen-audio has no built-in voices: a description in the prompt is the voice, and a
# fixed seed keeps the sentences of one reply in the same one (Q64i). Female teachers,
# like the voices above.
QWEN_AUDIO_VOICES: Mapping[Language, str] = {
    "en-US": "A friendly female American English teacher",
    "en-GB": "A friendly female British English teacher",
    "zh-CN": "A friendly female Mandarin Chinese teacher",
}
QWEN_AUDIO_SEED = 20261012
QWEN_AUDIO_SAMPLE_RATE = 24000
# One retry after a 429 (Bailian allows 3 requests a second, Q64l), waiting what
# Retry-After says, within reason.
DEFAULT_RETRY_AFTER = 1.0
MAX_RETRY_AFTER = 10.0


@dataclass(frozen=True)
class Speech:
    audio: bytes
    connection: str
    model: str
    voice: str
    mime_type: str = MIME_TYPE


class SpeechSynthesisError(Exception):
    """Every model in the route failed; the last error is chained."""


class NoVoiceError(SpeechSynthesisError):
    """No model in the route has a voice for the language: the browser reads it instead."""


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
    if is_qwen_audio(model):  # before the "tts" check: its names contain "tts" too
        return QWEN_AUDIO_VOICES[language]
    lowered = name.lower()
    if "kokoro" in lowered:
        return KOKORO_VOICES.get(language)
    if "cosyvoice" in lowered:
        return f"{name}:{COSYVOICE_VOICE}"
    if model.kind == "openai" or "tts" in lowered:
        return OPENAI_VOICE
    return None


def is_qwen_audio(model: ResolvedModel) -> bool:
    return model.model.lower().startswith("qwen-audio")


def qwen_audio_prompt(voice: str, text: str) -> str:
    """The prompt reading `text` in the described voice. The text is quoted and the
    reading pinned to it word for word, so a line like "add rain sounds" is read, not
    obeyed (Q64j)."""
    quoted = text.replace("\\", "\\\\").replace('"', '\\"')
    return (
        f"{voice.strip().rstrip('.')} reads the following text aloud word for word, "
        f'with no sound effects or background sound: "{quoted}"'
    )


def retry_after(response: httpx2.Response) -> float:
    """Seconds a 429 asks to wait: Retry-After in seconds, else a second."""
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return DEFAULT_RETRY_AFTER
    return min(max(seconds, 0.0), MAX_RETRY_AFTER)


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
        candidates = self.candidates(language)
        if not candidates:
            raise NoVoiceError(f"no text-to-speech model has a {language} voice")
        last_error: Exception | None = None
        for i, (model, voice) in enumerate(candidates):
            started = time.monotonic()
            try:
                audio = await _synthesize(model, text, language, voice, speed)
            except Exception as exc:
                last_error = exc
                self._record(model, i, started, text, user_id, background, error=exc)
                continue
            self._record(model, i, started, text, user_id, background)
            return Speech(audio=audio, connection=model.connection, model=model.model, voice=voice)
        raise SpeechSynthesisError(
            f"every text-to-speech model failed on {language}"
        ) from last_error

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


def _client(model: ResolvedModel) -> httpx2.AsyncClient:
    timeout = float(model.params.get("timeout") or DEFAULT_TIMEOUT)
    return make_async_http_client(
        allow_private=get_settings().provider_allow_private_networks, timeout=timeout
    )


async def _synthesize(
    model: ResolvedModel, text: str, language: Language, voice: str, speed: float
) -> bytes:
    if is_qwen_audio(model):
        return await _qwen_audio(model, text, voice, speed)
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
    async with _client(model) as client:
        if isinstance(body, str):
            response = await client.post(url, headers=headers, content=body.encode())
        else:
            response = await client.post(url, headers=headers, json=body)
    if response.status_code != 200:
        raise EndpointError(response.status_code, response.text.strip()[:200])
    if not response.content:
        raise EndpointError(response.status_code, "empty audio")
    return response.content


async def _qwen_audio(model: ResolvedModel, text: str, voice: str, speed: float) -> bytes:
    """POST the prompt to the workspace's `tts_url`, then GET the audio it links to."""
    url = model.params.get("tts_url")
    if not url:
        raise ProviderConfigError(
            f"connection {model.connection!r} needs tts_url, the Bailian workspace address, "
            "to read aloud with qwen-audio"
        )
    key = model.api_key.get_secret_value() if model.api_key else None
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    body = {
        "model": model.model,
        "input": {
            "text_prompt": qwen_audio_prompt(voice, text),
            "format": "mp3",
            "sample_rate": QWEN_AUDIO_SAMPLE_RATE,
            "channels": 1,
            "rate": min(max(speed, 0.5), 2.0),
            "seed": QWEN_AUDIO_SEED,
        },
    }
    async with _client(model) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.status_code == 429:
            await asyncio.sleep(retry_after(response))
            response = await client.post(url, headers=headers, json=body)
        if response.status_code != 200:
            raise EndpointError(response.status_code, response.text.strip()[:200])
        try:
            audio_url = response.json()["output"]["audio"]["url"]
        except (ValueError, KeyError, TypeError):
            audio_url = None
        if not isinstance(audio_url, str) or not audio_url:
            raise EndpointError(response.status_code, "no audio url")
        # A signed storage link: the key stays with the API.
        audio = await client.get(audio_url)
    if audio.status_code != 200:
        raise EndpointError(audio.status_code, "audio download failed")
    if not audio.content:
        raise EndpointError(audio.status_code, "empty audio")
    return audio.content


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
