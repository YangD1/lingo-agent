import base64
import io
import json
import uuid
import wave
from typing import Any

import httpx2
import pytest

from app.providers import pronunciation
from app.providers.config import RouteSpec, resolve_route
from app.providers.errors import NoModelConfiguredError
from app.usage import recorder
from app.usage.recorder import UsageRecord
from tests.unit.provider_fixtures import conn, make_config, make_ctx

# IPA script g (U+0261) is written escaped: ruff flags it as a look-alike of g.
PRESETS = {
    "openai": {"kind": "openai", "base_url": "https://openai.example.com/v1"},
    "azure": {"kind": "azure_speech", "base_url": "https://eastasia.tts.speech.microsoft.com"},
    "azure2": {"kind": "azure_speech", "base_url": "https://eastus.tts.speech.microsoft.com"},
}
STT_HOST = "eastasia.stt.speech.microsoft.com"


def wav(seconds: float = 1.0, *, rate: int = 16_000, channels: int = 1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(channels)
        clip.setsampwidth(2)
        clip.setframerate(rate)
        clip.writeframes(b"\x00\x00" * channels * int(rate * seconds))
    return buffer.getvalue()


# Shaped like Azure's documented short-audio response, trimmed.
AZURE_OK = {
    "RecognitionStatus": "Success",
    "Offset": 700000,
    "Duration": 8400000,
    "NBest": [
        {
            "Confidence": 0.98,
            "Lexical": "good morning",
            "Display": "Good morning.",
            "AccuracyScore": 88.0,
            "FluencyScore": 100.0,
            "CompletenessScore": 66.7,
            "ProsodyScore": 87.8,
            "PronScore": 84.2,
            "Words": [
                {
                    "Word": "good",
                    "AccuracyScore": 100.0,
                    "ErrorType": "None",
                    "Phonemes": [
                        {"Phoneme": "\u0261", "AccuracyScore": 100.0},
                        {"Phoneme": "ʊ", "AccuracyScore": 100.0},
                        {"Phoneme": "d", "AccuracyScore": 100.0},
                    ],
                },
                {
                    # The SDK-style nesting is accepted too.
                    "Word": "morning",
                    "PronunciationAssessment": {
                        "AccuracyScore": 41.0,
                        "ErrorType": "Mispronunciation",
                    },
                    "Phonemes": [{"PronunciationAssessment": {"AccuracyScore": 30.0}}],
                },
                {"Word": "everyone", "AccuracyScore": 0.0, "ErrorType": "Omission"},
            ],
        }
    ],
}


@pytest.fixture
def usage() -> Any:
    records: list[UsageRecord] = []
    recorder.set_usage_sink(records.append)
    yield records
    recorder.set_usage_sink(None)


def serve(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, httpx2.Response]
) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return responses[request.url.host]

    def client(*, allow_private: bool, timeout: float | None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))

    monkeypatch.setattr(pronunciation, "make_async_http_client", client)
    return seen


@pytest.fixture
def assessor(monkeypatch: pytest.MonkeyPatch) -> Any:
    def build(*refs: str) -> pronunciation.PronunciationAssessor:
        config = make_config(
            presets=PRESETS,
            llm={"default": ["openai:m"]},
            pronunciation={"default": ["azure:pronunciation"]},
        )
        monkeypatch.setattr(pronunciation, "get_providers_config", lambda: config)
        ctx = make_ctx(
            conn("openai"),
            conn("azure", "azure_speech", base_url=PRESETS["azure"]["base_url"]),
            conn("azure2", "azure_speech", base_url=PRESETS["azure2"]["base_url"]),
            routes={("pronunciation", "default"): RouteSpec(models=list(refs))},
        )
        return pronunciation.get_pronunciation(ctx)

    return build


def test_wav_must_be_16k_mono_and_at_most_30_seconds() -> None:
    assert pronunciation.wav_seconds(wav(2.5)) == 2.5
    assert pronunciation.wav_seconds(wav(30)) == 30
    for bad in (wav(31), wav(1, rate=44_100), wav(1, channels=2), b"RIFF0000WEBM", b""):
        with pytest.raises(pronunciation.InvalidAudioError):
            pronunciation.wav_seconds(bad)


def test_stt_url_follows_the_connection_region() -> None:
    assert pronunciation.azure_stt_url("https://eastasia.tts.speech.microsoft.com/") == (
        "https://eastasia.stt.speech.microsoft.com"
        "/speech/recognition/conversation/cognitiveservices/v1"
    )
    assert pronunciation.azure_stt_url("https://chinaeast2.tts.speech.azure.cn").startswith(
        "https://chinaeast2.stt.speech.azure.cn/"
    )


def test_prosody_is_asked_for_american_english_only() -> None:
    us = pronunciation.azure_params("Hi.", "en-US")
    gb = pronunciation.azure_params("Hi.", "en-GB")
    assert us["EnableProsodyAssessment"] == "True"
    assert "EnableProsodyAssessment" not in gb
    for params in (us, gb):
        assert params["GradingSystem"] == "HundredMark"
        assert params["Granularity"] == "Phoneme"
        assert params["EnableMiscue"] == "True"


async def test_azure_request_and_parsed_result(
    assessor: Any, monkeypatch: pytest.MonkeyPatch, usage: list[UsageRecord]
) -> None:
    seen = serve(monkeypatch, {STT_HOST: httpx2.Response(200, json=AZURE_OK)})
    user = uuid.uuid4()
    audio = wav(2.0)

    result = await assessor("azure:pronunciation").assess(
        audio, reference_text="Good morning, everyone.", language="en-US", user_id=user
    )

    (request,) = seen
    assert request.url.path == "/speech/recognition/conversation/cognitiveservices/v1"
    assert dict(request.url.params) == {"language": "en-US", "format": "detailed"}
    assert request.headers["ocp-apim-subscription-key"] == "sk-test"
    assert request.headers["content-type"] == pronunciation.CONTENT_TYPE
    sent = json.loads(base64.b64decode(request.headers["pronunciation-assessment"]))
    assert sent["ReferenceText"] == "Good morning, everyone."
    assert request.content == audio

    assert result.scores == pronunciation.Scores(
        overall=84.2, accuracy=88.0, fluency=100.0, completeness=66.7, prosody=87.8
    )
    assert result.recognized_text == "Good morning."
    good, morning, everyone = result.words
    assert (good.error, good.accuracy, [p.phoneme for p in good.phonemes]) == (
        "none",
        100.0,
        ["\u0261", "ʊ", "d"],
    )
    # Phoneme names missing (e.g. en-GB): scores only.
    assert (morning.error, morning.accuracy) == ("mispronunciation", 41.0)
    assert morning.phonemes == (pronunciation.PhonemeScore(phoneme=None, accuracy=30.0),)
    # An omitted word has no score, not a zero.
    assert (everyone.error, everyone.accuracy) == ("omission", None)
    assert (result.audio_seconds, result.connection, result.model) == (
        2.0,
        "azure",
        "pronunciation",
    )

    (record,) = usage
    assert (record.task, record.audio_seconds, record.input_tokens, record.user_id) == (
        "pronunciation",
        2.0,
        0,
        user,
    )
    assert (record.status, record.is_fallback) == ("ok", False)


async def test_falls_back_to_the_next_connection(
    assessor: Any, monkeypatch: pytest.MonkeyPatch, usage: list[UsageRecord]
) -> None:
    serve(
        monkeypatch,
        {
            STT_HOST: httpx2.Response(401, text="bad key"),
            "eastus.stt.speech.microsoft.com": httpx2.Response(200, json=AZURE_OK),
        },
    )

    result = await assessor("azure:pronunciation", "azure2:pronunciation").assess(
        wav(), reference_text="Good morning.", language="en-GB"
    )

    assert result.connection == "azure2"
    assert [(r.status, r.error_code, r.is_fallback) for r in usage] == [
        ("error", "EndpointError", False),
        ("ok", None, True),
    ]


async def test_silence_is_not_a_vendor_failure(
    assessor: Any, monkeypatch: pytest.MonkeyPatch, usage: list[UsageRecord]
) -> None:
    seen = serve(
        monkeypatch,
        {STT_HOST: httpx2.Response(200, json={"RecognitionStatus": "InitialSilenceTimeout"})},
    )

    with pytest.raises(pronunciation.NoSpeechError):
        await assessor("azure:pronunciation", "azure2:pronunciation").assess(
            wav(), reference_text="Hi.", language="en-US"
        )

    # Not retried elsewhere: the next vendor would hear silence too. Still billed.
    assert len(seen) == 1
    assert [r.status for r in usage] == ["ok"]


async def test_every_model_failing_raises(assessor: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {STT_HOST: httpx2.Response(200, json={"RecognitionStatus": "Error"})})
    with pytest.raises(pronunciation.AssessmentError) as info:
        await assessor("azure:pronunciation").assess(wav(), reference_text="Hi.", language="en-US")
    assert isinstance(info.value.__cause__, pronunciation.EndpointError)

    serve(monkeypatch, {STT_HOST: httpx2.Response(200, json={"unexpected": True})})
    with pytest.raises(pronunciation.AssessmentError):
        await assessor("azure:pronunciation").assess(wav(), reference_text="Hi.", language="en-US")


async def test_bad_audio_never_reaches_the_vendor(
    assessor: Any, monkeypatch: pytest.MonkeyPatch, usage: list[UsageRecord]
) -> None:
    seen = serve(monkeypatch, {})
    with pytest.raises(pronunciation.InvalidAudioError):
        await assessor("azure:pronunciation").assess(
            wav(31), reference_text="Hi.", language="en-US"
        )
    assert seen == [] and usage == []


def test_section_is_optional_and_azure_only() -> None:
    llm = {"default": ["openai:m"]}
    config = make_config(
        presets=PRESETS, llm=llm, pronunciation={"default": ["azure:pronunciation"]}
    )
    ctx = make_ctx(conn("azure", "azure_speech"))
    assert [m.model for m in resolve_route(config, ctx, "pronunciation", "default")] == [
        "pronunciation"
    ]
    for cfg, tenant in ((make_config(), ctx), (config, make_ctx(conn("openai")))):
        with pytest.raises(NoModelConfiguredError) as info:
            resolve_route(cfg, tenant, "pronunciation", "default")
        assert info.value.code == "no_pronunciation_model"
    with pytest.raises(ValueError, match="cannot assess pronunciation"):
        make_config(presets=PRESETS, llm=llm, pronunciation={"default": ["openai:whisper-1"]})
