import json
import uuid
from typing import Any

import httpx2
import pytest
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.providers import asr, llm
from app.providers.config import RouteSpec, resolve_route, resolve_route_with_source
from app.providers.errors import NoModelConfiguredError
from app.usage import recorder
from app.usage.recorder import UsageRecord
from tests.unit.provider_fixtures import TENANT, conn, make_config, make_ctx

# --- vision: explicit models only (ADR 0008 §5) --------------------------------------


def vision_config(**overrides: Any) -> Any:
    return make_config(
        llm={
            "default": ["deepseek:deepseek-chat"],
            "routes": {"chat": ["deepseek:deepseek-chat"], "vision": ["openai:gpt-5-mini"]},
        },
        **overrides,
    )


def test_vision_uses_its_own_route() -> None:
    ctx = make_ctx(conn("deepseek"), conn("openai"))
    chain = resolve_route(vision_config(), ctx, "llm", "vision")
    assert [(m.connection, m.model) for m in chain] == [("openai", "gpt-5-mini")]


def test_vision_never_borrows_default_models() -> None:
    # The tenant has a chat connection with a default model, but none for vision:
    # guessing that deepseek-chat can see images would let it invent their content.
    ctx = make_ctx(conn("deepseek", default_model="deepseek-chat"))

    with pytest.raises(NoModelConfiguredError) as info:
        resolve_route(vision_config(), ctx, "llm", "vision")

    assert info.value.code == "no_vision_model"
    # ... while chat still falls back as before (ADR 0007).
    assert resolve_route(vision_config(), ctx, "llm", "chat")


def test_vision_never_uses_the_llm_default_route() -> None:
    config = make_config()  # no vision route in this deployment's YAML
    ctx = make_ctx(conn("deepseek"), conn("openai"))

    with pytest.raises(NoModelConfiguredError) as info:
        resolve_route(config, ctx, "llm", "vision")
    assert info.value.code == "no_vision_model"


def test_a_tenant_can_pick_its_vision_model() -> None:
    ctx = make_ctx(
        conn("relay", "openai_compatible"),
        routes={("llm", "vision"): RouteSpec(models=["relay:qwen-vl"])},
    )
    chain, source = resolve_route_with_source(vision_config(), ctx, "llm", "vision")
    assert ([m.model for m in chain], source) == (["qwen-vl"], "override")


# --- asr section ------------------------------------------------------------------------

ASR_PRESETS = {
    "deepseek": {"kind": "deepseek", "base_url": "https://api.deepseek.com/v1"},
    "openai": {"kind": "openai", "base_url": "https://api.openai.com/v1"},
    "groq": {"kind": "openai_compatible", "base_url": "https://api.groq.com/openai/v1"},
}


def test_asr_section_resolves_like_other_sections() -> None:
    config = make_config(
        presets=ASR_PRESETS,
        asr={"default": ["groq:whisper-large-v3-turbo", "openai:gpt-transcribe"]},
    )
    ctx = make_ctx(conn("openai"), conn("groq", "openai_compatible"))

    chain = resolve_route(config, ctx, "asr", "default")

    assert [m.model for m in chain] == ["whisper-large-v3-turbo", "gpt-transcribe"]


def test_asr_rejects_vendors_without_a_transcription_api() -> None:
    with pytest.raises(ValueError, match="speech-to-text"):
        make_config(presets=ASR_PRESETS, asr={"default": ["deepseek:deepseek-chat"]})


def test_missing_asr_means_not_configured() -> None:
    ctx = make_ctx(conn("openai", default_model="gpt-5-mini"))
    for config in (make_config(), make_config(asr={"default": ["openai:gpt-transcribe"]})):
        if config.asr is not None:
            ctx = make_ctx()  # has the section, but no connection for it
        with pytest.raises(NoModelConfiguredError) as info:
            resolve_route(config, ctx, "asr", "default")
        assert info.value.code == "no_asr_model"


# --- structured output method -----------------------------------------------------------


class Answer(BaseModel):
    value: str


def test_openai_compatible_structured_output_uses_tool_calling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(
        embedding=None,
        llm={"default": ["relay:m1", "openai:gpt-5-mini"]},
        presets={
            "relay": {"kind": "openai_compatible", "base_url": "https://relay.example.com/v1"},
            "openai": {"kind": "openai", "base_url": "https://api.openai.com/v1"},
        },
    )
    monkeypatch.setattr(llm, "get_providers_config", lambda: config)
    llm._models.clear()
    methods: list[str] = []
    real = ChatOpenAI.with_structured_output

    def spy(self: ChatOpenAI, schema: Any, *, method: str = "default", **kwargs: Any) -> Any:
        methods.append(method)
        return real(self, schema, **({"method": method} if method != "default" else {}), **kwargs)

    monkeypatch.setattr(ChatOpenAI, "with_structured_output", spy)
    ctx = make_ctx(conn("relay", "openai_compatible"), conn("openai"))

    llm.get_structured_llm(ctx, "chat", Answer)

    assert methods == ["function_calling", "default"]
    llm._models.clear()


# --- speech-to-text client --------------------------------------------------------------


def json_response(body: Any, status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status, content=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )


@pytest.fixture
def usage() -> Any:
    records: list[UsageRecord] = []
    recorder.set_usage_sink(records.append)
    yield records
    recorder.set_usage_sink(None)


def serve(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, httpx2.Response]
) -> list[httpx2.Request]:
    """Answer each connection's base URL host with a canned response."""
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return responses[request.url.host]

    def client(model: Any) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key="k",
            base_url=model.base_url,
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
        )

    monkeypatch.setattr(asr, "_client", client)
    return seen


def stt(*names: str) -> asr.SpeechToText:
    config = make_config(
        presets={
            n: {"kind": "openai_compatible", "base_url": f"https://{n}.example.com/v1"}
            for n in names
        },
        llm={"default": [f"{names[0]}:m"]},
        asr={"default": [f"{n}:whisper-{n}" for n in names]},
        embedding=None,
    )
    ctx = make_ctx(*(conn(n, "openai_compatible") for n in names))
    return asr.SpeechToText(TENANT, tuple(resolve_route(config, ctx, "asr", "default")))


async def test_transcribe_posts_the_audio_and_records_usage(
    monkeypatch: pytest.MonkeyPatch, usage: list[UsageRecord]
) -> None:
    seen = serve(
        monkeypatch,
        {
            "a.example.com": json_response(
                {
                    "text": " I goed home. ",
                    "languages": [{"code": "en"}],
                    "usage": {"type": "duration", "seconds": 3.5},
                }
            )
        },
    )
    user, conversation = uuid.uuid4(), uuid.uuid4()

    transcript = await stt("a").transcribe(
        b"OggS-audio",
        filename="rec.ogg",
        mime_type="audio/ogg",
        user_id=user,
        conversation_id=conversation,
    )

    assert transcript == asr.Transcript("I goed home.", "en", 3.5)
    (request,) = seen
    assert request.url.path == "/v1/audio/transcriptions"
    body = request.read()
    assert b'name="model"\r\n\r\nwhisper-a' in body
    assert b'name="response_format"\r\n\r\njson' in body
    assert b"OggS-audio" in body and b'filename="rec.ogg"' in body
    (record,) = usage
    assert (record.task, record.connection_name, record.model, record.status) == (
        "asr",
        "a",
        "whisper-a",
        "ok",
    )
    assert (record.user_id, record.conversation_id, record.audio_seconds) == (
        user,
        conversation,
        3.5,
    )


async def test_transcribe_falls_back_and_reads_verbose_duration(
    monkeypatch: pytest.MonkeyPatch, usage: list[UsageRecord]
) -> None:
    serve(
        monkeypatch,
        {
            "a.example.com": json_response({"error": {"message": "sk-secret bad"}}, 401),
            "b.example.com": json_response({"text": "hello", "duration": 2}),
        },
    )

    transcript = await stt("a", "b").transcribe(b"x", filename="r.webm", mime_type="audio/webm")

    assert transcript == asr.Transcript("hello", None, 2.0)
    assert [(r.connection_name, r.status, r.is_fallback) for r in usage] == [
        ("a", "error", False),
        ("b", "ok", True),
    ]
    assert usage[0].error_code == "AuthenticationError"  # class name, never the message


async def test_transcribe_raises_when_every_model_fails(
    monkeypatch: pytest.MonkeyPatch, usage: list[UsageRecord]
) -> None:
    serve(monkeypatch, {"a.example.com": json_response({"error": {}}, 500)})

    with pytest.raises(asr.TranscriptionError) as info:
        await stt("a").transcribe(b"x", filename="r.webm", mime_type="audio/webm")

    assert getattr(info.value.__cause__, "status_code", None) == 500
