import json
import uuid
from typing import Any

import httpx2
import pytest

from app.providers import tts
from app.providers.config import ProviderKind, ResolvedModel, RouteSpec
from app.providers.errors import NoModelConfiguredError
from app.usage import recorder
from app.usage.recorder import UsageRecord
from tests.unit.provider_fixtures import TENANT, conn, make_config, make_ctx

PRESETS = {
    "openai": {"kind": "openai", "base_url": "https://openai.example.com/v1"},
    "azure": {"kind": "azure_speech", "base_url": "https://eastasia.tts.speech.microsoft.com"},
    "sf": {"kind": "openai_compatible", "base_url": "https://sf.example.com/v1"},
    "local": {"kind": "openai_compatible", "base_url": "https://local.example.com/v1"},
}


def model(connection: str, name: str, kind: ProviderKind) -> ResolvedModel:
    return ResolvedModel(connection, kind, name, f"https://{connection}.example.com/v1", None)


@pytest.mark.parametrize(
    ("name", "kind", "language", "voice"),
    [
        # Azure: the model is the voice for its own locale ...
        ("en-US-AvaMultilingualNeural", "azure_speech", "en-US", "en-US-AvaMultilingualNeural"),
        # ... a multilingual one reads other languages too ...
        ("en-US-AvaMultilingualNeural", "azure_speech", "zh-CN", "en-US-AvaMultilingualNeural"),
        # ... but a British learner gets a British voice, not an American reading.
        ("en-US-AvaMultilingualNeural", "azure_speech", "en-GB", "en-GB-SoniaNeural"),
        ("en-US-JennyNeural", "azure_speech", "zh-CN", "zh-CN-XiaoxiaoMultilingualNeural"),
        ("speaches-ai/Kokoro-82M-v1.0-ONNX", "openai_compatible", "en-GB", "bf_emma"),
        # speaches' Kokoro can't read Mandarin (espeak has no "zh").
        ("speaches-ai/Kokoro-82M-v1.0-ONNX", "openai_compatible", "zh-CN", None),
        (
            "FunAudioLLM/CosyVoice2-0.5B",
            "openai_compatible",
            "en-US",
            "FunAudioLLM/CosyVoice2-0.5B:anna",
        ),
        ("gpt-4o-mini-tts", "openai", "zh-CN", "coral"),
        ("tts-1", "openai_compatible", "en-US", "coral"),  # an OpenAI model behind a relay
        ("my-voice-server", "openai_compatible", "en-US", None),  # unknown: needs a voice
    ],
)
def test_default_voice(name: str, kind: ProviderKind, language: tts.Language, voice: str) -> None:
    assert tts.default_voice(model("c", name, kind), language) == voice


def test_ssml_escapes_text_and_sets_the_rate() -> None:
    ssml = tts.azure_ssml("Tom & <Jerry>", "en-US", "en-US-AvaNeural", 0.9)
    assert ssml == (
        '<speak version=\'1.0\' xml:lang="en-US"><voice xml:lang="en-US" '
        'name="en-US-AvaNeural"><prosody rate="-10%">Tom &amp; &lt;Jerry&gt;</prosody>'
        "</voice></speak>"
    )
    assert tts.azure_rate(1.0) == "+0%"
    assert tts.azure_rate(1.2) == "+20%"


@pytest.fixture
def usage() -> Any:
    records: list[UsageRecord] = []
    recorder.set_usage_sink(records.append)
    yield records
    recorder.set_usage_sink(None)


def serve(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, httpx2.Response]
) -> list[httpx2.Request]:
    """Answer each connection's host with a canned response."""
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return responses[request.url.host]

    def client(*, allow_private: bool, timeout: float | None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))

    monkeypatch.setattr(tts, "make_async_http_client", client)
    return seen


def mp3(data: bytes = b"ID3-audio") -> httpx2.Response:
    return httpx2.Response(200, content=data, headers={"content-type": "audio/mpeg"})


@pytest.fixture
def speaker(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Builds a TextToSpeech from a tenant route, through get_tts."""

    def build(*refs: str, voices: dict[str, Any] | None = None) -> tts.TextToSpeech:
        config = make_config(
            presets=PRESETS, llm={"default": ["openai:m"]}, tts={"default": [refs[0]]}
        )
        monkeypatch.setattr(tts, "get_providers_config", lambda: config)
        ctx = make_ctx(
            conn("openai"),
            conn("azure", "azure_speech", base_url=PRESETS["azure"]["base_url"]),
            conn("sf", "openai_compatible"),
            conn("local", "openai_compatible", key=None),
            routes={
                ("tts", "default"): RouteSpec(models=list(refs), params={"voices": voices or {}})
            },
        )
        return tts.get_tts(ctx)

    return build


async def test_openai_style_request_and_usage_by_characters(
    speaker: Any, monkeypatch: pytest.MonkeyPatch, usage: list[UsageRecord]
) -> None:
    seen = serve(monkeypatch, {"sf.example.com": mp3()})
    user = uuid.uuid4()

    speech = await speaker("sf:FunAudioLLM/CosyVoice2-0.5B").synthesize(
        "Nice to meet you.", language="en-US", speed=0.9, user_id=user
    )

    assert speech == tts.Speech(
        b"ID3-audio", "sf", "FunAudioLLM/CosyVoice2-0.5B", "FunAudioLLM/CosyVoice2-0.5B:anna"
    )
    (request,) = seen
    assert str(request.url) == "https://sf.example.com/v1/audio/speech"
    assert request.headers["authorization"] == "Bearer sk-test"
    assert json.loads(request.content) == {
        "model": "FunAudioLLM/CosyVoice2-0.5B",
        "input": "Nice to meet you.",
        "voice": "FunAudioLLM/CosyVoice2-0.5B:anna",
        "speed": 0.9,
        "response_format": "mp3",
    }
    (record,) = usage
    assert (record.task, record.characters, record.input_tokens, record.user_id) == (
        "tts",
        17,
        0,
        user,
    )
    assert (record.status, record.is_fallback, record.background) == ("ok", False, False)


async def test_azure_request_sends_ssml_with_the_key(
    speaker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = serve(monkeypatch, {"eastasia.tts.speech.microsoft.com": mp3()})

    speech = await speaker("azure:en-US-AvaMultilingualNeural").synthesize("你好", language="zh-CN")

    assert speech.voice == "en-US-AvaMultilingualNeural"
    (request,) = seen
    assert str(request.url) == "https://eastasia.tts.speech.microsoft.com/cognitiveservices/v1"
    assert request.headers["ocp-apim-subscription-key"] == "sk-test"
    assert request.headers["x-microsoft-outputformat"] == "audio-24khz-48kbitrate-mono-mp3"
    assert request.headers["content-type"] == "application/ssml+xml"
    assert "user-agent" in request.headers
    assert 'xml:lang="zh-CN"' in request.content.decode()
    assert ">你好</prosody>" in request.content.decode()


async def test_falls_back_and_skips_models_without_a_voice(
    speaker: Any, monkeypatch: pytest.MonkeyPatch, usage: list[UsageRecord]
) -> None:
    seen = serve(
        monkeypatch,
        {"sf.example.com": httpx2.Response(503, text="busy"), "openai.example.com": mp3(b"ok")},
    )
    # local:custom has no built-in voice and no override, so it is never called.
    tts_ = speaker("sf:FunAudioLLM/CosyVoice2-0.5B", "local:custom", "openai:gpt-4o-mini-tts")

    speech = await tts_.synthesize("Hi", language="en-US", background=True)

    assert (speech.connection, speech.audio) == ("openai", b"ok")
    assert [r.url.host for r in seen] == ["sf.example.com", "openai.example.com"]
    assert [(r.status, r.error_code, r.is_fallback, r.background) for r in usage] == [
        ("error", "EndpointError", False, True),
        ("ok", None, True, True),
    ]


async def test_route_voices_override_the_built_in_ones(
    speaker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = serve(monkeypatch, {"local.example.com": mp3()})
    tts_ = speaker("local:custom", voices={"local:custom": {"en-GB": "my-british"}})

    assert tts_.candidates("en-US") == []
    speech = await tts_.synthesize("Hi", language="en-GB")

    assert speech.voice == "my-british"
    assert json.loads(seen[0].content)["voice"] == "my-british"
    assert "authorization" not in seen[0].headers  # keyless local server


async def test_every_model_failing_raises(speaker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"openai.example.com": httpx2.Response(200, content=b"")})
    with pytest.raises(tts.SpeechSynthesisError) as info:
        await speaker("openai:tts-1").synthesize("Hi", language="en-US")
    assert isinstance(info.value.__cause__, tts.EndpointError)

    with pytest.raises(tts.NoVoiceError):  # nothing can read this language
        await speaker("local:custom").synthesize("Hi", language="en-US")


def test_no_tts_route_means_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts, "get_providers_config", make_config)
    with pytest.raises(NoModelConfiguredError) as info:
        tts.get_tts(make_ctx(conn("openai")))
    assert info.value.code == "no_tts_model"


def test_tenant_ids_are_kept(speaker: Any) -> None:
    assert speaker("openai:tts-1").tenant_id == TENANT
