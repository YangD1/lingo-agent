"""Tenant-scoped pronunciation assessment: scoring a learner reading a sentence aloud
against that sentence (ADR 0028 §5).

The first adapter is Azure's short-audio speech-to-text REST API with the
`Pronunciation-Assessment` header, reached through an `azure_speech` connection - the
same one that reads aloud. The browser encodes the recording as 16 kHz mono 16-bit WAV
(the API takes no webm and the backend has no ffmpeg), at most 30 seconds.

    assessor = get_pronunciation(ctx)
    result = await assessor.assess(wav, reference_text="Nice to meet you.", language="en-US")

Models in the route are tried in order. Each attempt is written to llm_usage by audio
seconds, not tokens. Phoneme names, syllables and prosody come for en-US only; other
accents get phoneme scores without names.
"""

import base64
import io
import json
import time
import uuid
import wave
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.providers.config import (
    PRONUNCIATION_KINDS,
    ResolvedModel,
    TenantProviderContext,
    resolve_route,
)
from app.providers.errors import ProviderConfigError
from app.providers.llm import get_providers_config
from app.providers.net_guard import make_async_http_client
from app.settings import get_settings
from app.usage.recorder import UsageRecord, submit_usage

type Language = Literal["en-US", "en-GB"]
LANGUAGES: tuple[Language, ...] = ("en-US", "en-GB")

SAMPLE_RATE = 16_000
MAX_SECONDS = 30.0  # Azure's limit for pronunciation assessment on short audio
CONTENT_TYPE = "audio/wav; codecs=audio/pcm; samplerate=16000"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = "lingo-agent"
# Azure reports times in 100-nanosecond ticks.
TICKS_PER_SECOND = 10_000_000

type WordError = Literal["none", "omission", "insertion", "mispronunciation"]
_WORD_ERRORS: dict[str, WordError] = {
    "None": "none",
    "Omission": "omission",
    "Insertion": "insertion",
    "Mispronunciation": "mispronunciation",
}


class InvalidAudioError(ValueError):
    """The recording isn't 16 kHz mono 16-bit WAV, or is longer than 30 seconds."""


class NoSpeechError(Exception):
    """The service heard nothing it could match (silence, noise or another language)."""


class AssessmentError(Exception):
    """Every model in the route failed; the last error is chained."""


class EndpointError(Exception):
    """The vendor answered with an error status; the message is safe to log."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"HTTP {status}: {message}")


def wav_seconds(audio: bytes) -> float:
    """The recording's length; raises InvalidAudioError unless it is what Azure takes."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as clip:
            channels, width, rate = clip.getnchannels(), clip.getsampwidth(), clip.getframerate()
            frames = clip.getnframes()
    except (wave.Error, EOFError) as exc:
        raise InvalidAudioError(f"not a WAV file: {exc}") from exc
    if (channels, width, rate) != (1, 2, SAMPLE_RATE):
        raise InvalidAudioError(
            f"expected 16 kHz mono 16-bit, got {rate} Hz, {channels} channel(s), {width * 8}-bit"
        )
    seconds = frames / SAMPLE_RATE
    if seconds > MAX_SECONDS:
        raise InvalidAudioError(f"{seconds:.1f} s is longer than {MAX_SECONDS:.0f} s")
    return seconds


# What the learner sees, stored as JSONB in pronunciation_attempts (ADR 0028 §6).


class PhonemeScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    phoneme: str | None  # IPA; None where Azure gives scores only (not en-US)
    accuracy: float


class WordScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    word: str
    # None for an omitted word: there is nothing to score.
    accuracy: float | None
    error: WordError
    phonemes: tuple[PhonemeScore, ...] = ()


class Scores(BaseModel):
    """0-100 each. `overall` is Azure's PronScore, weighted from the others."""

    model_config = ConfigDict(frozen=True)

    overall: float
    accuracy: float
    fluency: float
    completeness: float
    prosody: float | None = None  # en-US only


class Assessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    scores: Scores
    words: tuple[WordScore, ...]
    recognized_text: str
    audio_seconds: float
    connection: str
    model: str


# Azure's response. The REST API puts scores on each item; the SDK's JSON nests them
# under "PronunciationAssessment". Both are accepted.


class _Lifted(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _lift(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(
            nested := data.get("PronunciationAssessment"), dict
        ):
            return {**data, **nested}
        return data


class _AzurePhoneme(_Lifted):
    phoneme: str | None = Field(None, validation_alias="Phoneme")
    accuracy: float = Field(validation_alias="AccuracyScore")


class _AzureWord(_Lifted):
    word: str = Field(validation_alias="Word")
    accuracy: float | None = Field(None, validation_alias="AccuracyScore")
    error: str = Field("None", validation_alias="ErrorType")
    phonemes: list[_AzurePhoneme] = Field([], validation_alias="Phonemes")


class _AzureBest(_Lifted):
    display: str = Field("", validation_alias=AliasChoices("Display", "Lexical"))
    accuracy: float = Field(validation_alias="AccuracyScore")
    fluency: float = Field(validation_alias="FluencyScore")
    completeness: float = Field(validation_alias="CompletenessScore")
    prosody: float | None = Field(None, validation_alias="ProsodyScore")
    overall: float = Field(validation_alias="PronScore")
    words: list[_AzureWord] = Field([], validation_alias="Words")


class _AzureResult(BaseModel):
    status: str = Field(validation_alias="RecognitionStatus")
    best: list[_AzureBest] = Field([], validation_alias="NBest")


def azure_params(reference_text: str, language: Language) -> dict[str, str]:
    params = {
        "ReferenceText": reference_text,
        "GradingSystem": "HundredMark",
        "Granularity": "Phoneme",
        "Dimension": "Comprehensive",
        # Marks omitted and inserted words against the reference text.
        "EnableMiscue": "True",
        "PhonemeAlphabet": "IPA",
    }
    if language == "en-US":  # prosody is assessed for en-US only
        params["EnableProsodyAssessment"] = "True"
    return params


def azure_header(reference_text: str, language: Language) -> str:
    raw = json.dumps(azure_params(reference_text, language), ensure_ascii=False)
    return base64.b64encode(raw.encode()).decode()


def azure_stt_url(base_url: str) -> str:
    """The connection's base_url is the text-to-speech host (ADR 0028, task 53); speech
    recognition is the same region's `.stt.` host."""
    host = base_url.rstrip("/").replace(".tts.speech.", ".stt.speech.", 1)
    return f"{host}/speech/recognition/conversation/cognitiveservices/v1"


def parse_azure(payload: Any, *, audio_seconds: float, model: ResolvedModel) -> Assessment:
    try:
        result = _AzureResult.model_validate(payload)
    except ValidationError as exc:
        raise EndpointError(200, f"unexpected response: {exc.error_count()} error(s)") from exc
    if result.status != "Success" or not result.best:
        # NoMatch, InitialSilenceTimeout, BabbleTimeout: the learner's side, not the vendor's.
        if result.status in ("NoMatch", "InitialSilenceTimeout", "BabbleTimeout"):
            raise NoSpeechError(result.status)
        raise EndpointError(200, f"recognition status {result.status}")
    best = result.best[0]
    return Assessment(
        scores=Scores(
            overall=best.overall,
            accuracy=best.accuracy,
            fluency=best.fluency,
            completeness=best.completeness,
            prosody=best.prosody,
        ),
        words=tuple(
            WordScore(
                word=w.word,
                accuracy=None if w.error == "Omission" else w.accuracy,
                error=_WORD_ERRORS.get(w.error, "none"),
                phonemes=tuple(
                    PhonemeScore(phoneme=p.phoneme or None, accuracy=p.accuracy) for p in w.phonemes
                ),
            )
            for w in best.words
        ),
        recognized_text=best.display,
        audio_seconds=audio_seconds,
        connection=model.connection,
        model=model.model,
    )


@dataclass(frozen=True)
class PronunciationAssessor:
    tenant_id: uuid.UUID
    models: tuple[ResolvedModel, ...]
    task: str = "pronunciation"  # llm_usage label; connection tests use their own

    async def assess(
        self,
        audio: bytes,
        *,
        reference_text: str,
        language: Language,
        user_id: uuid.UUID | None = None,
    ) -> Assessment:
        """Raises InvalidAudioError before calling anyone, NoSpeechError when the
        recording holds nothing to assess, AssessmentError when every model failed."""
        seconds = wav_seconds(audio)
        last_error: Exception | None = None
        for i, model in enumerate(self.models):
            started = time.monotonic()
            try:
                result = await _assess(model, audio, reference_text, language, seconds)
            except NoSpeechError:
                # The vendor did its job (and bills for it); another one would hear silence too.
                self._record(model, i, started, seconds, user_id)
                raise
            except Exception as exc:
                last_error = exc
                self._record(model, i, started, seconds, user_id, error=exc)
                continue
            self._record(model, i, started, seconds, user_id)
            return result
        raise AssessmentError("every pronunciation model failed") from last_error

    def _record(
        self,
        model: ResolvedModel,
        position: int,
        started: float,
        seconds: float,
        user_id: uuid.UUID | None,
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
                # Billed by the audio sent, failed requests included when they reached it.
                audio_seconds=seconds,
            )
        )


async def _assess(
    model: ResolvedModel, audio: bytes, reference_text: str, language: Language, seconds: float
) -> Assessment:
    key = model.api_key.get_secret_value() if model.api_key else None
    headers = {
        "Content-Type": CONTENT_TYPE,
        "Accept": "application/json",
        "Pronunciation-Assessment": azure_header(reference_text, language),
        "User-Agent": USER_AGENT,
    }
    if key:
        headers["Ocp-Apim-Subscription-Key"] = key
    timeout = float(model.params.get("timeout") or DEFAULT_TIMEOUT)
    async with make_async_http_client(
        allow_private=get_settings().provider_allow_private_networks, timeout=timeout
    ) as client:
        response = await client.post(
            azure_stt_url(model.base_url),
            params={"language": language, "format": "detailed"},
            headers=headers,
            content=audio,
        )
    if response.status_code != 200:
        raise EndpointError(response.status_code, response.text.strip()[:200])
    try:
        payload = response.json()
    except ValueError as exc:
        raise EndpointError(200, "response is not JSON") from exc
    return parse_azure(payload, audio_seconds=seconds, model=model)


def get_pronunciation(ctx: TenantProviderContext) -> PronunciationAssessor:
    """Raises NoModelConfiguredError (code `no_pronunciation_model`) when nothing is
    configured."""
    resolved = resolve_route(get_providers_config(), ctx, "pronunciation", "default")
    for model in resolved:
        if model.kind not in PRONUNCIATION_KINDS:  # routes are validated on save; YAML at startup
            raise ProviderConfigError(
                f"connection {model.connection!r} cannot assess pronunciation"
            )
    return PronunciationAssessor(ctx.tenant_id, tuple(resolved))
