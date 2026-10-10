"""The settings API for word pronunciations generated ahead of time (task 55.3)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Word
from app.services.speech.worker import WordAudioWorker
from tests.integration import test_word_audio
from tests.integration.test_word_audio import Vendor

# The fake vendor of the service tests.
vendor = test_word_audio.vendor

PRICE = 15.0


class Gate:
    """A pace that waits until the test opens the gate; says when the worker got there."""

    def __init__(self) -> None:
        self.reached, self.open = asyncio.Event(), asyncio.Event()
        self.open.set()

    async def __call__(self, seconds: float) -> None:
        self.reached.set()
        await self.open.wait()

    def close(self) -> None:
        self.reached.clear()
        self.open.clear()


@pytest.fixture(autouse=True)
async def gate(app: FastAPI) -> AsyncIterator[Gate]:
    """The worker paces requests and backs off without actually waiting (gate open)."""
    real = app.state.word_audio_worker
    gate = Gate()
    app.state.word_audio_worker = WordAudioWorker(app.state.sessionmaker, sleep=gate)
    yield gate
    gate.open.set()
    await app.state.word_audio_worker.stop()
    app.state.word_audio_worker = real


async def setup(client: AsyncClient, session: AsyncSession, *, azure: bool = False) -> None:
    response = await client.post(
        "/auth/register", json={"email": "owner@example.com", "password": "password123"}
    )
    assert response.status_code == 201
    if azure:
        connection = {
            "name": "azure",
            "kind": "azure_speech",
            "base_url": "https://eastasia.tts.speech.microsoft.com",
            "api_key": "0123456789abcdef",
        }
        models = ["azure:en-US-AvaMultilingualNeural"]
    else:
        connection = {
            "name": "one",
            "kind": "openai_compatible",
            "base_url": "https://one.example.com/v1",
            "api_key": "sk-test-0123456789",
        }
        models = ["one:tts-1"]
    response = await client.post("/tenant/connections", json=connection)
    assert response.status_code == 201, response.text
    response = await client.put("/tenant/routes/tts/default", json={"models": models})
    assert response.status_code == 200, response.text
    session.add_all(
        [
            Word(word="apple", translation="苹果", tags=["cet4"]),
            Word(word="banana", translation="香蕉", tags=["cet4", "gre"]),
            Word(word="cherry", translation="樱桃", tags=["gre"]),
        ]
    )
    await session.commit()


async def get(client: AsyncClient, url: str = "/tenant/word-audio", **params: Any) -> Any:
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def start(**extra: Any) -> dict[str, Any]:
    return {"book_id": "cet4", "accents": ["en-US", "en-GB"], "requests_per_minute": 60, **extra}


def book(body: dict[str, Any], book_id: str) -> dict[str, Any]:
    return next(b for b in body["books"] if b["book_id"] == book_id)


async def test_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/tenant/word-audio")).status_code == 401


async def test_without_a_route_nothing_can_start(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post("/auth/register", json={"email": "a@example.com", "password": "password123"})

    body = await get(client)
    assert (body["available"], body["voices"], body["job"]) == (False, {}, None)
    response = await client.get(
        "/tenant/word-audio/estimate", params={"book_id": "cet4", "accents": ["en-US"]}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_tts_model"
    response = await client.post("/tenant/word-audio/jobs", json=start())
    assert response.status_code == 409


async def test_estimate_then_run_a_book(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, vendor: Vendor
) -> None:
    await setup(client, db_session)

    estimate = await get(
        client,
        "/tenant/word-audio/estimate",
        book_id="cet4",
        accents=["en-US", "en-GB"],
        price_per_million=PRICE,
    )
    assert estimate["words"] == 2
    assert estimate["voices"]["en-US"] == {"connection": "one", "model": "tts-1", "voice": "coral"}
    assert (estimate["pieces"], estimate["existing"]) == (4, 0)
    assert estimate["characters"] == 2 * len("applebanana")
    assert estimate["cost"] == PRICE * 22 / 1_000_000
    # Not Azure: no suggested price, 60 requests a minute.
    assert (estimate["requests_per_minute"], estimate["suggested_price"]) == (60, None)
    assert estimate["minutes"] == 1

    response = await client.post(
        "/tenant/word-audio/jobs", json=start(price_per_million=PRICE, currency=" USD ")
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "running"
    again = await client.post("/tenant/word-audio/jobs", json=start(book_id="gre"))
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "job_active"
    await app.state.word_audio_worker.wait_idle()

    body = await get(client)
    job = body["job"]
    assert (job["status"], job["done"], job["failed"], job["total"]) == ("done", 4, 0, 4)
    assert (job["characters"], job["currency"]) == (22, "USD")
    assert job["cost"] == PRICE * 22 / 1_000_000
    assert book(body, "cet4") == {
        "book_id": "cet4",
        "words": 2,
        "made": {"en-US": 2, "en-GB": 2},
    }
    # "banana" is in GRE too.
    assert book(body, "gre")["made"] == {"en-US": 1, "en-GB": 1}
    assert (body["count"], body["old_count"]) == (4, 0)
    assert body["bytes"] == job["bytes"] > 0

    # A GRE job makes only "cherry".
    estimate = await get(
        client, "/tenant/word-audio/estimate", book_id="gre", accents=["en-US", "en-GB"]
    )
    assert (estimate["existing"], estimate["characters"]) == (2, 2 * len("cherry"))


async def test_azure_suggests_its_price_and_pace(
    client: AsyncClient, db_session: AsyncSession, vendor: Vendor
) -> None:
    await setup(client, db_session, azure=True)

    estimate = await get(client, "/tenant/word-audio/estimate", book_id="cet4", accents=["en-GB"])

    assert estimate["voices"]["en-GB"]["voice"] == "en-GB-SoniaNeural"
    assert (estimate["requests_per_minute"], estimate["suggested_price"]) == (20, 15.0)
    assert estimate["cost"] is None


async def test_pause_resume_cancel(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, vendor: Vendor, gate: Gate
) -> None:
    await setup(client, db_session)
    assert (await client.post("/tenant/word-audio/jobs/current/pause")).status_code == 404

    gate.close()
    await client.post("/tenant/word-audio/jobs", json=start())
    await gate.reached.wait()  # after the first request
    paused = await client.post("/tenant/word-audio/jobs/current/pause")
    assert paused.json()["status"] == "paused"
    gate.open.set()
    await app.state.word_audio_worker.wait_idle()
    job = (await get(client))["job"]
    # It finished the word it was on (both accents), then stopped.
    assert (job["status"], job["done"]) == ("paused", 2)
    # A paused job's audio can't be deleted from under it.
    response = await client.delete("/tenant/word-audio", params={"book_id": "cet4"})
    assert response.status_code == 409

    gate.close()
    resumed = await client.post("/tenant/word-audio/jobs/current/resume")
    assert resumed.json()["status"] == "running"
    await gate.reached.wait()
    cancelled = await client.post("/tenant/word-audio/jobs/current/cancel")
    assert cancelled.json()["status"] == "cancelled"
    gate.open.set()
    await app.state.word_audio_worker.wait_idle()
    job = (await get(client))["job"]
    assert (job["status"], job["done"]) == ("cancelled", 4)
    assert (await client.post("/tenant/word-audio/jobs/current/resume")).status_code == 404


async def test_delete_old_voices_and_books(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, vendor: Vendor
) -> None:
    await setup(client, db_session)
    await client.post("/tenant/word-audio/jobs", json=start(accents=["en-US"]))
    await app.state.word_audio_worker.wait_idle()
    # The deployment picks another American voice (Q55b): the audio made is now old.
    response = await client.put(
        "/tenant/routes/tts/default",
        json={"models": ["one:tts-1"], "params": {"voices": {"one:tts-1": {"en-US": "nova"}}}},
    )
    assert response.status_code == 200, response.text

    body = await get(client)
    assert book(body, "cet4")["made"] == {"en-US": 0, "en-GB": 0}
    assert (body["count"], body["old_count"]) == (2, 2)
    assert (await client.delete("/tenant/word-audio")).status_code == 422

    response = await client.delete("/tenant/word-audio", params={"old": True})
    assert response.json()["deleted"] == 2
    assert (await get(client))["count"] == 0

    await client.post("/tenant/word-audio/jobs", json=start(book_id="gre", accents=["en-US"]))
    await app.state.word_audio_worker.wait_idle()
    response = await client.delete("/tenant/word-audio", params={"book_id": "cet4"})
    # "banana" goes with CET-4, though GRE has it too.
    assert response.json()["deleted"] == 1
    assert book(await get(client), "gre")["made"]["en-US"] == 1
