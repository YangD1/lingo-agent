"""Tenant-scoped text-to-speech: the server reads aloud (ADR 0018 §3, ADR 0028 §3).

Four kinds of endpoint:
- OpenAI's `POST /audio/speech` (OpenAI, SiliconFlow, a local speaches with Kokoro);
- Azure's text-to-speech REST API, SSML in, mp3 out (`azure_speech` connections);
- Alibaba Bailian (DashScope), both answering with a link to the audio, fetched in a
  second request: qwen3-tts-flash, fast, with named voices and no speed control, for
  reading aloud (task 64.2b); qwen-audio, slow (13-27 s a sentence), the voice described
  in a prompt, for word pronunciations made ahead of time (task 64.2a).

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
from typing import Any, Literal
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

import httpx2

from app.providers.config import (
    TTS_KINDS,
    ProvidersConfig,
    ResolvedModel,
    TenantProviderContext,
    context_for,
    resolve_route,
    route_for,
)
from app.providers.errors import NoModelConfiguredError, ProviderConfigError
from app.providers.llm import get_providers_config
from app.providers.net_guard import make_async_http_client
from app.settings import get_settings
from app.usage.recorder import UsageRecord, submit_usage

type Language = Literal["en-US", "en-GB", "zh-CN"]
LANGUAGES: tuple[Language, ...] = ("en-US", "en-GB", "zh-CN")

MIME_TYPE = "audio/mpeg"
WAV_MIME_TYPE = "audio/wav"
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
# Measured 13.6-27.2 s a sentence (task 64.2).
QWEN_AUDIO_TIMEOUT = 60.0
# Without `tts_url`, the region's shared host takes the request (task 64.2: no workspace
# needed); both paths are under the connection's own host.
QWEN_AUDIO_PATH = "/api/v1/services/audio/tts/SpeechSynthesizer"
QWEN_TTS_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
# qwen3-tts-flash's named voices (Q64q, the full list is in tts_voices.py). None is
# British: a British learner's sentences go to the next model, or the browser.
QWEN_TTS_VOICES: Mapping[Language, str] = {"en-US": "Jennifer", "zh-CN": "Cherry"}
QWEN_TTS_LANGUAGES: Mapping[Language, str] = {
    "en-US": "English",
    "en-GB": "English",
    "zh-CN": "Chinese",
}
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
    # How much faster the player should play it: the speed asked for, when the model
    # can't read at that speed itself (qwen3-tts-flash, Q64p); else 1.
    playback_rate: float = 1.0


@dataclass(frozen=True)
class _Synthesized:
    audio: bytes
    mime_type: str = MIME_TYPE
    input_tokens: int = 0
    output_tokens: int = 0


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
    if is_qwen_tts(model):
        return QWEN_TTS_VOICES.get(language)
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


def is_qwen_tts(model: ResolvedModel) -> bool:
    """qwen3-tts-flash and its snapshots; not the realtime ones, which need a WebSocket."""
    name = model.model.lower()
    return name.startswith("qwen3-tts") and "realtime" not in name


def synthesis_speed(model: ResolvedModel, speed: float) -> float:
    """The speed `model` is asked to read at: 1 when it can't change speed (Q64p)."""
    return 1.0 if is_qwen_tts(model) else speed


def dashscope_url(model: ResolvedModel, path: str) -> str:
    """`path` on the connection's own host (https://dashscope.aliyuncs.com for the
    preset's base_url .../compatible-mode/v1)."""
    parts = urlsplit(model.base_url)
    return f"{parts.scheme}://{parts.netloc}{path}"


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

    @property
    def cache_tenant_id(self) -> uuid.UUID:
        """Whose read-aloud cache this route's audio goes in: the main account's when a
        member reads with its connection, so members share it (ADR 0031 §7, Q65h)."""
        billed = self.models[0].billed_tenant_id if self.models else None
        return billed or self.tenant_id

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
            read_at = synthesis_speed(model, speed)
            try:
                made = await _synthesize(model, text, language, voice, read_at)
            except Exception as exc:
                last_error = exc
                self._record(model, i, started, text, user_id, background, error=exc)
                continue
            self._record(model, i, started, text, user_id, background, made=made)
            return Speech(
                audio=made.audio,
                connection=model.connection,
                model=model.model,
                voice=voice,
                mime_type=made.mime_type,
                playback_rate=round(speed / read_at, 2),
            )
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
        made: _Synthesized | None = None,
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
                # Only qwen-audio reports tokens; the rest bill by characters.
                input_tokens=made.input_tokens if made else 0,
                output_tokens=made.output_tokens if made else 0,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="error" if error is not None else "ok",
                is_fallback=position > 0,
                # The class name only: messages can echo request details.
                error_code=type(error).__name__[:64] if error is not None else None,
                # Vendors bill a failed request too when it reached them; count what was sent.
                characters=len(text),
                background=background,
                billed_tenant_id=model.billed_tenant_id,
                section="tts",
            )
        )


def _timeout(model: ResolvedModel, model_default: float) -> float:
    """A timeout the tenant set wins; the deployment's default only when it's longer than
    the model's own (task 64.2: a 30 s default cut qwen-audio's 13-30 s calls off, Q64t)."""
    value = model.params.get("timeout")
    if not value:
        return model_default
    if "timeout" in model.deployment_defaults:
        return max(float(value), model_default)
    return float(value)


def _client(model: ResolvedModel, default_timeout: float = DEFAULT_TIMEOUT) -> httpx2.AsyncClient:
    return make_async_http_client(
        allow_private=get_settings().provider_allow_private_networks,
        timeout=_timeout(model, default_timeout),
    )


async def _synthesize(
    model: ResolvedModel, text: str, language: Language, voice: str, speed: float
) -> _Synthesized:
    if is_qwen_audio(model):
        return await _qwen_audio(model, text, voice, speed)
    if is_qwen_tts(model):
        return await _qwen_tts(model, text, language, voice)
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
    return _Synthesized(response.content)


async def _qwen_audio(model: ResolvedModel, text: str, voice: str, speed: float) -> _Synthesized:
    """POST the prompt to `tts_url` (a workspace's host, or else the connection's own),
    then GET the audio it links to."""
    url = model.params.get("tts_url") or dashscope_url(model, QWEN_AUDIO_PATH)
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
    answer, audio = await _post_then_fetch(model, url, body, QWEN_AUDIO_TIMEOUT)
    usage = answer.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return _Synthesized(
        audio,
        input_tokens=_count(usage.get("input_tokens")),
        output_tokens=_count(usage.get("output_tokens")),
    )


async def _qwen_tts(
    model: ResolvedModel, text: str, language: Language, voice: str
) -> _Synthesized:
    """qwen3-tts-flash: a named voice, always at its own speed, wav only (Q64p, Q64r)."""
    body = {
        "model": model.model,
        "input": {"text": text, "voice": voice, "language_type": QWEN_TTS_LANGUAGES[language]},
    }
    _, audio = await _post_then_fetch(model, dashscope_url(model, QWEN_TTS_PATH), body)
    return _Synthesized(audio, mime_type=WAV_MIME_TYPE)


def _count(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


async def _post_then_fetch(
    model: ResolvedModel,
    url: str,
    body: Mapping[str, object],
    default_timeout: float = DEFAULT_TIMEOUT,
) -> tuple[dict[str, Any], bytes]:
    """DashScope's synthesis: POST, wait out one 429, then GET the audio the answer links
    to (a signed storage link, valid a day). Returns the answer and the audio."""
    key = model.api_key.get_secret_value() if model.api_key else None
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with _client(model, default_timeout) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.status_code == 429:
            await asyncio.sleep(retry_after(response))
            response = await client.post(url, headers=headers, json=body)
        if response.status_code != 200:
            raise EndpointError(response.status_code, response.text.strip()[:200])
        try:
            answer = response.json()
            audio_url = answer["output"]["audio"]["url"]
        except (ValueError, KeyError, TypeError):
            answer, audio_url = {}, None
        if not isinstance(audio_url, str) or not audio_url:
            raise EndpointError(response.status_code, "no audio url")
        # The key stays with the API.
        audio = await client.get(audio_url)
    if audio.status_code != 200:
        raise EndpointError(audio.status_code, "audio download failed")
    if not audio.content:
        raise EndpointError(audio.status_code, "empty audio")
    return answer, audio.content


# The route for word pronunciations made ahead of time (Q64s): a slow, good voice can make
# them without slowing replies read aloud. Empty means the same as `default`.
WORDS_TASK = "words"


def tts_task(config: ProvidersConfig, ctx: TenantProviderContext, task: str) -> str:
    """The route `task` reads with: one with no model this tenant can use reads like the
    default one, unless the tenant switched its models off (ADR 0026)."""
    if task == "default":
        return task
    try:
        resolve_route(config, ctx, "tts", task)
    except NoModelConfiguredError as exc:
        return task if exc.code == "models_disabled" else "default"
    return task


def get_tts(ctx: TenantProviderContext, task: str = "default") -> TextToSpeech:
    """Raises NoModelConfiguredError (code `no_tts_model`) when nothing is configured."""
    config = get_providers_config()
    task = tts_task(config, ctx, task)
    resolved = resolve_route(config, ctx, "tts", task)
    for model in resolved:
        if model.kind not in TTS_KINDS:  # routes are validated on save; YAML at startup
            raise ProviderConfigError(f"connection {model.connection!r} cannot read text aloud")
    # Voice overrides are the route's own params (ADR 0028 §3): the main account's when
    # the route is (ADR 0031 §5).
    voices = (
        route_for(config, context_for(config, ctx, "tts", task), "tts", task).params.get("voices")
        or {}
    )
    return TextToSpeech(ctx.tenant_id, tuple(resolved), voices)
