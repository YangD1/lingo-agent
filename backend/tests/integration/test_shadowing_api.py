"""Shadowing endpoints, capabilities and the review card's mark (task 56.4)."""

from typing import Any

import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PronunciationAttempt, Word
from app.providers import asr, pronunciation
from app.providers.asr import Transcript
from tests.unit.test_pronunciation import wav

AZURE_KEY = "azure-key-0123456789"


def assessed(morning: float = 40.0) -> dict[str, Any]:
    return {
        "RecognitionStatus": "Success",
        "NBest": [
            {
                "Display": "Good morning, everyone.",
                "AccuracyScore": 80.0,
                "FluencyScore": 90.0,
                "CompletenessScore": 100.0,
                "ProsodyScore": 70.0,
                "PronScore": 82.0,
                "Words": [
                    {"Word": "good", "AccuracyScore": 95.0, "ErrorType": "None"},
                    {"Word": "morning", "AccuracyScore": morning, "ErrorType": "Mispronunciation"},
                    {"Word": "everyone", "AccuracyScore": 85.0, "ErrorType": "None"},
                ],
            }
        ],
    }


@pytest.fixture
def azure(monkeypatch: pytest.MonkeyPatch) -> list[httpx2.Response]:
    """Answers queued per request."""
    responses: list[httpx2.Response] = []

    def client(*, allow_private: bool, timeout: float | None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: responses.pop(0)))

    monkeypatch.setattr(pronunciation, "make_async_http_client", client)
    return responses


@pytest.fixture(autouse=True)
async def words(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Word(word="good", translation="好", frq=100),
            Word(word="morning", translation="早上", frq=800),
            Word(word="everyone", translation="每个人", frq=2500),
        ]
    )
    await db_session.commit()


async def register(client: AsyncClient, email: str = "a@example.com") -> None:
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201


async def with_azure(client: AsyncClient) -> None:
    response = await client.post(
        "/tenant/connections", json={"preset": "azure", "api_key": AZURE_KEY}
    )
    assert response.status_code == 201, response.text


async def with_asr(client: AsyncClient, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    response = await client.post(
        "/tenant/connections",
        json={
            "name": "stt",
            "kind": "openai_compatible",
            "base_url": "https://stt.example.com/v1",
            "api_key": "sk-test-0123456789",
        },
    )
    assert response.status_code == 201, response.text
    response = await client.put("/tenant/routes/asr/default", json={"models": ["stt:whisper-1"]})
    assert response.status_code == 200, response.text

    async def transcribe(self: Any, audio: bytes, **_: Any) -> Transcript:
        return Transcript(text)

    monkeypatch.setattr(asr.SpeechToText, "transcribe", transcribe)


async def post(client: AsyncClient, audio: bytes | None = None, **fields: str) -> httpx2.Response:
    data = {
        "reference_text": "Good morning, everyone.",
        "language": "en-US",
        "source": "reading",
        "source_id": "42",
    } | fields
    return await client.post(  # type: ignore[return-value]
        "/speech/shadowing",
        data=data,
        files={"file": ("shadowing.wav", audio if audio is not None else wav(2.0), "audio/wav")},
    )


async def capabilities(client: AsyncClient) -> Any:
    return (await client.get("/speech/capabilities")).json()["shadowing"]


async def test_nothing_configured_means_no_shadowing(client: AsyncClient) -> None:
    await register(client)

    assert await capabilities(client) is None
    response = await post(client)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_configured"


async def test_assessed_reading_is_kept_and_marks_the_card(
    client: AsyncClient, azure: list[httpx2.Response], db_session: AsyncSession
) -> None:
    await register(client)
    await with_azure(client)
    assert await capabilities(client) == "assessment"
    azure.append(httpx2.Response(200, json=assessed()))

    response = await post(client)

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["mode"], body["counted"], body["source"], body["source_id"]) == (
        "assessment",
        True,
        "reading",
        "42",
    )
    assert body["scores"]["overall"] == 82.0 and body["scores"]["prosody"] == 70.0
    assert [w["word"] for w in body["words"]] == ["good", "morning", "everyone"]
    assert body["mispronounced"] == ["morning"]
    # The recording itself is not stored anywhere.
    row = await db_session.scalar(select(PronunciationAttempt))
    assert row is not None and not hasattr(row, "audio")

    # Review cards say which words the learner doesn't say right.
    await client.post("/vocab/mine", json={"word": "morning"})
    await client.post("/vocab/mine", json={"word": "good"})
    page = (await client.get("/vocab/mine")).json()
    assert {w["word"]["word"]: w["mispronounced"] for w in page["words"]} == {
        "morning": True,
        "good": False,
    }

    # A better reading later clears the mark.
    azure.append(httpx2.Response(200, json=assessed(morning=90.0)))
    assert (await post(client)).json()["mispronounced"] == []
    page = (await client.get("/vocab/mine")).json()
    assert not any(w["mispronounced"] for w in page["words"])


async def test_rough_result_from_a_transcript(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register(client)
    await with_asr(client, monkeypatch, "good evening everyone")
    assert await capabilities(client) == "rough"

    response = await post(client, language="en-GB", source="chat")

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["mode"], body["fallback_reason"], body["scores"], body["counted"]) == (
        "rough",
        "not_configured",
        None,
        False,
    )
    assert [(w["word"], w["status"]) for w in body["words"]] == [
        ("Good", "none"),
        ("morning", "substitution"),
        ("everyone", "none"),
    ]


@pytest.mark.parametrize(
    ("audio", "fields", "status", "code"),
    [
        (wav(31), {}, 422, "invalid_audio"),
        (b"RIFF....WEBMvp8", {}, 422, "invalid_audio"),
        (b"\x00" * (1024 * 1024 + 1), {}, 413, "recording_too_large"),
        (None, {"reference_text": "   "}, 422, "invalid_reference"),
    ],
)
async def test_bad_requests(
    client: AsyncClient,
    azure: list[httpx2.Response],
    audio: bytes | None,
    fields: dict[str, str],
    status: int,
    code: str,
) -> None:
    await register(client)
    await with_azure(client)

    response = await post(client, audio, **fields)

    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
    assert azure == []  # never reached the vendor


async def test_invalid_fields_are_rejected(client: AsyncClient) -> None:
    await register(client)
    for fields in (
        {"language": "zh-CN"},
        {"source": "elsewhere"},
        {"reference_text": "x" * 601},
        {"source_id": "x" * 65},
    ):
        assert (await post(client, **fields)).status_code == 422, fields


async def test_silence_and_vendor_failure(
    client: AsyncClient, azure: list[httpx2.Response]
) -> None:
    await register(client)
    await with_azure(client)
    azure.append(httpx2.Response(200, json={"RecognitionStatus": "InitialSilenceTimeout"}))
    response = await post(client)
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "no_speech")

    azure.append(httpx2.Response(503, text="busy"))
    response = await post(client)
    assert (response.status_code, response.json()["detail"]["code"]) == (502, "unavailable")


async def test_history_is_mine_and_can_be_deleted(
    client: AsyncClient, azure: list[httpx2.Response]
) -> None:
    await register(client)
    await with_azure(client)
    ids = []
    for _ in range(3):
        azure.append(httpx2.Response(200, json=assessed()))
        ids.append((await post(client)).json()["id"])

    first = (await client.get("/speech/shadowing", params={"limit": 2})).json()
    assert [i["id"] for i in first["items"]] == ids[:0:-1]
    rest = (
        await client.get("/speech/shadowing", params={"limit": 2, "before": first["next_before"]})
    ).json()
    assert [i["id"] for i in rest["items"]] == ids[:1] and rest["next_before"] is None

    assert (await client.delete(f"/speech/shadowing/{ids[0]}")).status_code == 204
    assert (await client.delete(f"/speech/shadowing/{ids[0]}")).status_code == 404

    # Someone else sees none of it and can't delete it.
    await client.post("/auth/logout")
    await register(client, "b@example.com")
    assert (await client.get("/speech/shadowing")).json() == {"items": [], "next_before": None}
    assert (await client.delete(f"/speech/shadowing/{ids[1]}")).status_code == 404
    assert (await client.delete("/speech/shadowing")).json() == {"deleted": 0}

    await client.post("/auth/logout")
    await client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert (await client.delete("/speech/shadowing")).json() == {"deleted": 2}
    assert (await client.get("/speech/shadowing")).json()["items"] == []
