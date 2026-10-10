"""Word pronunciations generated ahead of time (task 55.1, ADR 0028 §4)."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import TenantMember, TtsAudio, Word, WordAudioJob
from app.db.session import create_sessionmaker
from app.providers import tts
from app.providers.config import ResolvedModel, TenantProviderContext
from app.providers.tts import TextToSpeech
from app.services.speech import read_aloud, word_audio
from app.services.speech.word_audio import ActiveJobError, NoAccentError
from app.services.speech.worker import WordAudioWorker
from app.services.vocab.books import get_book

BOOK = get_book("cet4")
assert BOOK is not None


class Vendor:
    """A fake `/audio/speech`: audio named after the word, or a set status per word."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []
        self.status: dict[str, list[int]] = {}

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.asked.append((body["input"], body["voice"]))
        codes = self.status.get(body["input"])
        code = codes.pop(0) if codes else 200
        if code != 200:
            return httpx2.Response(code, content=b"no")
        return httpx2.Response(200, content=f"mp3:{body['input']}:{body['voice']}".encode())


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Vendor:
    fake = Vendor()

    def client(*, allow_private: bool, timeout: float | None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handle))

    monkeypatch.setattr(tts, "make_async_http_client", client)
    return fake


class Sleeps:
    def __init__(self) -> None:
        self.seconds: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


def model(connection: str = "kokoro", name: str = "speaches-ai/Kokoro-82M-v1.0-ONNX") -> Any:
    return ResolvedModel(
        connection, "openai_compatible", name, f"https://{connection}.example.com/v1", None
    )


async def tenant(client: AsyncClient, session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    response = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@example.com", "password": "password123"}
    )
    assert response.status_code == 201
    user_id = uuid.UUID(response.json()["id"])
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user_id)
    )
    assert tenant_id is not None
    return tenant_id, user_id


async def words(session: AsyncSession, *names: str) -> dict[str, int]:
    rows = [Word(word=name, translation="释义", tags=["cet4"]) for name in names]
    session.add_all(rows)
    session.add(Word(word="elsewhere", translation="释义", tags=["gre"]))
    await session.commit()
    return {w.word: w.id for w in rows}


async def pinned(session: AsyncSession, tenant_id: uuid.UUID) -> list[TtsAudio]:
    return list(
        await session.scalars(
            select(TtsAudio)
            .where(TtsAudio.tenant_id == tenant_id, TtsAudio.pinned.is_(True))
            .order_by(TtsAudio.word_id, TtsAudio.language)
        )
    )


async def run(session: AsyncSession, job_id: uuid.UUID, route: TextToSpeech, **kw: Any) -> int:
    batches = 1
    while await word_audio.run_batch(session, job_id, route, BOOK, **kw):
        batches += 1
    return batches


async def test_estimate_counts_what_is_left_to_make(
    client: AsyncClient, db_session: AsyncSession, vendor: Vendor
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    await words(db_session, "apple", "banana", "cherry")
    route = TextToSpeech(tenant_id, (model(),))
    # A learner already had "apple" read in American English.
    await read_aloud.read_aloud(
        db_session,
        _ctx(tenant_id),
        "apple",
        language="en-US",
        speed=1.0,
        user_id=user_id,
        tts=route,
    )

    estimate = await word_audio.estimate(
        db_session, route, BOOK, ["en-US", "en-GB"], price_per_million=15
    )

    assert estimate.words == 3
    assert estimate.voices["en-US"].voice == "af_heart"
    assert estimate.voices["en-GB"].voice == "bf_emma"
    assert estimate.missing == []
    assert (estimate.pieces, estimate.existing) == (6, 1)
    assert estimate.characters == len("banana") + len("cherry") + len("applebananacherry")
    assert estimate.bytes == 5 * word_audio.DEFAULT_BYTES_PER_WORD
    assert estimate.cost == pytest.approx(estimate.characters * 15 / 1_000_000)


async def test_a_job_reads_each_word_once_per_accent_and_pins_it(
    client: AsyncClient, db_session: AsyncSession, vendor: Vendor
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    ids = await words(db_session, "apple", "banana", "cherry")
    route = TextToSpeech(tenant_id, (model(), model("backup", "tts-1")))
    await read_aloud.read_aloud(
        db_session,
        _ctx(tenant_id),
        "apple",
        language="en-US",
        speed=1.0,
        user_id=user_id,
        tts=route,
    )
    vendor.asked.clear()
    sleeps = Sleeps()

    job = await word_audio.start(
        db_session, route, BOOK, ["en-US", "en-GB"], user_id=user_id, requests_per_minute=20
    )
    batches = await run(db_session, job.id, route, batch_size=2, sleep=sleeps)

    await db_session.refresh(job)
    assert batches == 3  # two batches, then one finding nothing left marks it done
    assert (job.status, job.total, job.done, job.failed) == ("done", 6, 6, 0)
    assert job.cursor == ids["cherry"]
    assert job.characters == len("banana") + len("cherry") + len("applebananacherry")
    assert job.finished_at is not None
    # Five requests, all to the first model; the learner's "apple" was pinned, not bought.
    assert len(vendor.asked) == 5
    assert ("apple", "af_heart") not in vendor.asked
    assert sleeps.seconds == [3.0] * 5
    rows = await pinned(db_session, tenant_id)
    assert [(r.word_id, r.language) for r in rows] == [
        (ids[w], accent) for w in ("apple", "banana", "cherry") for accent in ("en-GB", "en-US")
    ]
    assert all(r.user_id is None and r.connection_name == "kokoro" for r in rows)

    # A learner reading a word at speed 1.0 gets the audio generated ahead of time.
    heard = await read_aloud.read_aloud(
        db_session,
        _ctx(tenant_id),
        "banana",
        language="en-GB",
        speed=1.0,
        user_id=user_id,
        tts=route,
    )
    assert heard.cached and heard.audio == b"mp3:banana:bf_emma"


async def test_pause_resume_and_carry_on_after_a_restart(
    client: AsyncClient, db_session: AsyncSession, vendor: Vendor
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    await words(db_session, "apple", "banana", "cherry")
    route = TextToSpeech(tenant_id, (model(),))
    job = await word_audio.start(
        db_session, route, BOOK, ["en-US"], user_id=user_id, requests_per_minute=60
    )

    assert await word_audio.run_batch(db_session, job.id, route, BOOK, batch_size=1, sleep=Sleeps())
    paused = await word_audio.set_status(db_session, tenant_id, "pause")
    assert paused is not None and paused.status == "paused"
    assert not await word_audio.run_batch(db_session, job.id, route, BOOK, sleep=Sleeps())
    assert await word_audio.set_status(db_session, tenant_id, "pause") is None

    resumed = await word_audio.set_status(db_session, tenant_id, "resume")
    assert resumed is not None and resumed.status == "running"
    await run(db_session, job.id, route, sleep=Sleeps())

    await db_session.refresh(job)
    assert (job.status, job.done) == ("done", 3)
    assert [word for word, _ in vendor.asked] == ["apple", "banana", "cherry"]


async def test_one_active_job_per_tenant_and_cancel(
    client: AsyncClient, db_session: AsyncSession, vendor: Vendor
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    await words(db_session, "apple")
    route = TextToSpeech(tenant_id, (model(),))
    await word_audio.start(
        db_session, route, BOOK, ["en-US"], user_id=user_id, requests_per_minute=20
    )

    with pytest.raises(ActiveJobError):
        await word_audio.start(
            db_session, route, BOOK, ["en-GB"], user_id=user_id, requests_per_minute=20
        )
    cancelled = await word_audio.set_status(db_session, tenant_id, "cancel")
    assert cancelled is not None and cancelled.status == "cancelled"
    await word_audio.start(
        db_session, route, BOOK, ["en-GB"], user_id=user_id, requests_per_minute=20
    )


async def test_no_model_reads_the_accents(
    client: AsyncClient, db_session: AsyncSession, vendor: Vendor
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    # A model with no built-in voice and none set on the route.
    route = TextToSpeech(tenant_id, (model("custom", "my-voice-model"),))

    estimate = await word_audio.estimate(db_session, route, BOOK, ["en-US"])
    assert estimate.missing == ["en-US"] and estimate.pieces == 0
    with pytest.raises(NoAccentError):
        await word_audio.start(
            db_session, route, BOOK, ["en-US"], user_id=user_id, requests_per_minute=20
        )


async def test_rate_limits_back_off_and_failures_are_counted(
    client: AsyncClient, db_session: AsyncSession, vendor: Vendor
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    await words(db_session, "apple", "banana")
    route = TextToSpeech(tenant_id, (model(),))
    vendor.status = {"apple": [429, 200], "banana": [500]}
    sleeps = Sleeps()
    job = await word_audio.start(
        db_session, route, BOOK, ["en-US"], user_id=user_id, requests_per_minute=60
    )

    await run(db_session, job.id, route, sleep=sleeps)

    await db_session.refresh(job)
    assert (job.status, job.done, job.failed) == ("done", 1, 1)
    assert sleeps.seconds == [word_audio.RATE_LIMIT_BACKOFF[0], 1.0, 1.0]
    # Failed words are left out; a new job makes only those.
    again = await word_audio.estimate(db_session, route, BOOK, ["en-US"])
    assert (again.existing, again.characters) == (1, len("banana"))


async def test_failing_in_a_row_pauses_the_job(
    client: AsyncClient,
    db_session: AsyncSession,
    vendor: Vendor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(word_audio, "FAILURES_BEFORE_PAUSE", 2)
    tenant_id, user_id = await tenant(client, db_session)
    await words(db_session, "apple", "banana", "cherry")
    route = TextToSpeech(tenant_id, (model(),))
    vendor.status = {w: [401] for w in ("apple", "banana", "cherry")}
    job = await word_audio.start(
        db_session, route, BOOK, ["en-US"], user_id=user_id, requests_per_minute=60
    )

    assert not await word_audio.run_batch(db_session, job.id, route, BOOK, sleep=Sleeps())

    await db_session.refresh(job)
    assert (job.status, job.failed, job.error) == ("paused", 2, "2 words in a row failed")
    assert len(vendor.asked) == 2


async def test_a_model_gone_from_the_route_pauses_the_job(
    client: AsyncClient, db_session: AsyncSession, vendor: Vendor
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    await words(db_session, "apple")
    job = await word_audio.start(
        db_session,
        TextToSpeech(tenant_id, (model(),)),
        BOOK,
        ["en-US"],
        user_id=user_id,
        requests_per_minute=60,
    )

    changed = TextToSpeech(tenant_id, (model("backup", "tts-1"),))
    assert not await word_audio.run_batch(db_session, job.id, changed, BOOK, sleep=Sleeps())

    await db_session.refresh(job)
    assert job.status == "paused"
    assert job.error == "model kokoro:speaches-ai/Kokoro-82M-v1.0-ONNX left the route"
    assert vendor.asked == []
    assert await db_session.scalar(select(WordAudioJob.done).where(WordAudioJob.id == job.id)) == 0


def _ctx(tenant_id: uuid.UUID) -> TenantProviderContext:
    """read_aloud only reads the tenant id from the context when given a TextToSpeech."""
    return cast(TenantProviderContext, SimpleNamespace(tenant_id=tenant_id))


# The worker (task 55.2).


@pytest.fixture
async def maker(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # db_session's teardown truncates the tables after the test.
    yield create_sessionmaker(db_engine)


def kokoro(ctx: TenantProviderContext) -> TextToSpeech:
    return TextToSpeech(ctx.tenant_id, (model(),))


async def test_the_worker_runs_a_job_to_the_end(
    client: AsyncClient,
    db_session: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    vendor: Vendor,
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    await words(db_session, "apple", "banana")
    job = await word_audio.start(
        db_session,
        kokoro(_ctx(tenant_id)),
        BOOK,
        ["en-US", "en-GB"],
        user_id=user_id,
        requests_per_minute=60,
    )
    worker = WordAudioWorker(maker, route=kokoro, sleep=Sleeps())

    worker.submit(job.id)
    worker.submit(job.id)  # already running: no second task
    await worker.wait_idle()

    await db_session.refresh(job)
    assert (job.status, job.done) == ("done", 4)
    assert len(vendor.asked) == 4


async def test_a_restart_carries_on_running_jobs_only(
    client: AsyncClient,
    db_session: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    vendor: Vendor,
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    other_id, _ = await tenant(client, db_session)
    await words(db_session, "apple", "banana", "cherry")
    job = await word_audio.start(
        db_session,
        kokoro(_ctx(tenant_id)),
        BOOK,
        ["en-US"],
        user_id=user_id,
        requests_per_minute=60,
    )
    paused = await word_audio.start(
        db_session, kokoro(_ctx(other_id)), BOOK, ["en-US"], user_id=None, requests_per_minute=60
    )
    await word_audio.set_status(db_session, other_id, "pause")

    # The first process is stopped while waiting after its first word.
    reached, gate = asyncio.Event(), asyncio.Event()

    async def stuck(seconds: float) -> None:
        reached.set()
        await gate.wait()

    first = WordAudioWorker(maker, route=kokoro, sleep=stuck)
    first.submit(job.id)
    await reached.wait()
    await first.stop()
    await db_session.refresh(job)
    assert (job.status, job.cursor, job.done) == ("running", 0, 0)

    second = WordAudioWorker(maker, route=kokoro, sleep=Sleeps())
    assert await second.recover() == 1
    await second.wait_idle()

    await db_session.refresh(job)
    await db_session.refresh(paused)
    assert (job.status, job.done) == ("done", 3)
    assert paused.status == "paused"
    # "apple" was asked for again: the first process never saved it.
    assert [word for word, _ in vendor.asked] == ["apple", "apple", "banana", "cherry"]


async def test_without_a_route_the_worker_pauses_the_job(
    client: AsyncClient,
    db_session: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    vendor: Vendor,
) -> None:
    tenant_id, user_id = await tenant(client, db_session)
    await words(db_session, "apple")
    job = await word_audio.start(
        db_session,
        kokoro(_ctx(tenant_id)),
        BOOK,
        ["en-US"],
        user_id=user_id,
        requests_per_minute=60,
    )
    worker = WordAudioWorker(maker, sleep=Sleeps())  # the tenant's real route: none

    worker.submit(job.id)
    await worker.wait_idle()

    await db_session.refresh(job)
    assert (job.status, job.error) == ("paused", "no read-aloud route configured")
    assert vendor.asked == []
