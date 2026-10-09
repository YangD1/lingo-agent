import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.providers.model_catalog import (
    ANTHROPIC_VERSION,
    DiscoveredModel,
    ModelListError,
    categorize,
    fetch_models,
)
from app.providers.net_guard import make_async_http_client

KEY = SecretStr("sk-test-123")


def mock_client(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> tuple[httpx2.AsyncClient, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(record)), seen


def json_response(body: Any, status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status, content=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )


@pytest.mark.parametrize(
    ("model_id", "category"),
    [
        ("gpt-5-mini", "chat"),
        ("deepseek-chat", "chat"),
        ("claude-sonnet-5", "chat"),
        ("qwen3:8b", "chat"),
        ("text-embedding-3-small", "embedding"),
        ("bge-m3", "embedding"),
        ("whisper-1", "other"),
        ("tts-1-hd", "other"),
        ("gpt-4o-mini-transcribe", "other"),
        ("gpt-realtime", "other"),
        ("dall-e-3", "other"),
        # A local speaches server also lists VAD and TTS models.
        ("silero_vad_v5", "other"),
        ("speaches-ai/Kokoro-82M-v1.0-ONNX", "other"),
        ("rhasspy/piper-voices", "other"),
        ("Systran/faster-whisper-small", "other"),
        ("gpt-image-1", "other"),
        ("omni-moderation-latest", "other"),
        ("davinci-002", "other"),
    ],
)
def test_categorize(model_id: str, category: str) -> None:
    assert categorize(model_id) == category


async def test_openai_style_listing_is_sorted_and_deduplicated() -> None:
    client, seen = mock_client(
        lambda r: json_response(
            {
                "object": "list",
                "data": [
                    {"id": "gpt-5-mini"},
                    {"id": "a-model"},
                    {"id": "gpt-5-mini"},
                    {"no": "id"},
                ],
            }
        )
    )
    models = await fetch_models("openai", "https://relay.example.com/v1", KEY, client=client)

    assert models == [
        DiscoveredModel("a-model", "chat"),
        DiscoveredModel("gpt-5-mini", "chat"),
    ]
    assert str(seen[0].url) == "https://relay.example.com/v1/models"
    assert seen[0].headers["authorization"] == "Bearer sk-test-123"


async def test_keyless_openai_compatible_sends_no_auth_header() -> None:
    client, seen = mock_client(lambda r: json_response({"data": [{"id": "qwen3"}]}))
    await fetch_models("openai_compatible", "http://localhost:11434/v1", None, client=client)
    assert "authorization" not in seen[0].headers


async def test_azure_lists_the_voices_of_languages_read_aloud() -> None:
    voices = [
        {"ShortName": "zh-CN-XiaoxiaoNeural", "Locale": "zh-CN"},
        {"ShortName": "en-US-AvaMultilingualNeural", "Locale": "en-US"},
        {"ShortName": "fr-FR-DeniseNeural", "Locale": "fr-FR"},
        {"ShortName": "en-GB-SoniaNeural", "Locale": "en-GB"},
    ]
    client, seen = mock_client(lambda r: json_response(voices))  # type: ignore[arg-type]

    base = "https://eastasia.tts.speech.microsoft.com"
    models = await fetch_models("azure_speech", base, KEY, client=client)

    # Voices are never chat models, whatever their names look like.
    assert models == [
        DiscoveredModel("en-GB-SoniaNeural", "other"),
        DiscoveredModel("en-US-AvaMultilingualNeural", "other"),
        DiscoveredModel("zh-CN-XiaoxiaoNeural", "other"),
    ]
    assert str(seen[0].url) == f"{base}/cognitiveservices/voices/list"
    assert seen[0].headers["ocp-apim-subscription-key"] == "sk-test-123"


async def test_azure_unexpected_shape_is_a_model_list_error() -> None:
    client, _ = mock_client(lambda r: json_response({"data": []}))
    with pytest.raises(ModelListError, match="unexpected response shape"):
        await fetch_models("azure_speech", "https://x.example.com", KEY, client=client)


async def test_anthropic_listing_follows_pages() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if "after_id" not in request.url.params:
            return json_response(
                {"data": [{"id": "claude-b"}], "has_more": True, "last_id": "claude-b"}
            )
        return json_response(
            {"data": [{"id": "claude-a"}], "has_more": False, "last_id": "claude-a"}
        )

    client, seen = mock_client(handler)
    models = await fetch_models("anthropic", "https://api.anthropic.com", KEY, client=client)

    assert [m.id for m in models] == ["claude-a", "claude-b"]
    assert len(seen) == 2
    assert seen[0].url.path == "/v1/models"
    assert seen[1].url.params["after_id"] == "claude-b"
    assert seen[0].headers["x-api-key"] == "sk-test-123"
    assert seen[0].headers["anthropic-version"] == ANTHROPIC_VERSION
    assert "authorization" not in seen[0].headers


async def test_vendor_error_message_is_passed_on() -> None:
    client, _ = mock_client(
        lambda r: json_response({"error": {"message": "Incorrect API key provided"}}, status=401)
    )
    with pytest.raises(ModelListError, match="HTTP 401: Incorrect API key provided"):
        await fetch_models("openai", "https://api.openai.com/v1", KEY, client=client)


async def test_html_page_hints_at_a_wrong_base_url() -> None:
    client, _ = mock_client(lambda r: httpx2.Response(200, content=b"<html>hello</html>"))
    with pytest.raises(ModelListError, match="check the base URL"):
        await fetch_models("openai_compatible", "https://example.com", KEY, client=client)


async def test_network_failure_becomes_model_list_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    client, _ = mock_client(handler)
    with pytest.raises(ModelListError, match="ConnectError"):
        await fetch_models("openai", "https://api.openai.com/v1", KEY, client=client)


async def test_guarded_client_refuses_private_destinations() -> None:
    async with make_async_http_client(allow_private=False, timeout=5) as client:
        with pytest.raises(ModelListError, match=r"'127\.0\.0\.1' is not allowed"):
            await fetch_models("openai_compatible", "http://127.0.0.1:9/v1", None, client=client)
