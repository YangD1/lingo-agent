"""Word pronunciations generated ahead of time for a word book (ADR 0028 §4, task 55).

A deployment owner asks for a book in some accents; `estimate` says how many words,
characters, bytes and (at the price they give) how much, and `start` records a job.
`run_batch` then works through the book in word id order, a batch at a time, so a
restart or a pause carries on from `cursor`. Each word and accent is read once by the
first model in the route that reads that accent, fixed when the job starts (Q55c);
audio already cached under the same key is pinned instead of paid for again. Rows are
pinned (never evicted) and carry the word, so they can be counted and deleted per book.

Words are always read at speed 1.0: the page plays them faster or slower (Q55a).
Requests are paced to `requests_per_minute` (Q55e), counted from each request's start
and capped for vendors with an account limit (qwen-audio, task 64.2a); one word at a
time, so a slow model sets the pace instead (task 64.2: qwen-audio takes ~13 s a word).
A 429 backs off and retries, other failures are logged and counted and the job goes on,
until enough fail in a row that it pauses.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, and_, delete, false, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TtsAudio, Word, WordAudioJob
from app.providers.tts import (
    EndpointError,
    Language,
    SpeechSynthesisError,
    TextToSpeech,
    is_qwen_audio,
)
from app.services.speech.read_aloud import audio_key
from app.services.vocab.books import Book

logger = logging.getLogger(__name__)

type Accent = Language
ACCENTS: tuple[Accent, ...] = ("en-US", "en-GB")
WORD_SPEED = 1.0
USAGE_TASK = "word_audio"

BATCH_SIZE = 50
# A word in 48 kbit/s mp3 with Azure's leading and trailing silence; used until the
# tenant has some word audio of its own to average.
DEFAULT_BYTES_PER_WORD = 7_000
# Backoffs after a 429, in seconds; then the word counts as failed.
RATE_LIMIT_BACKOFF: tuple[float, ...] = (30, 60, 120)
# This many failures in a row (a revoked key, a vendor down) pauses the job.
FAILURES_BEFORE_PAUSE = 20
# Pacing suggested when starting (Q55e): Azure's free tier allows 20 requests a minute.
AZURE_REQUESTS_PER_MINUTE = 20
OTHER_REQUESTS_PER_MINUTE = 60
# Bailian's qwen-audio allows 3 requests a second for the whole account (Q64l): word audio
# never goes past 2, leaving room for replies read aloud meanwhile.
QWEN_AUDIO_MAX_REQUESTS_PER_MINUTE = 120
# A word takes this long on qwen-audio (12-13 s each, task 64.2): with one word at a time
# that, not the pace asked for, says how long a book takes (Q64u).
QWEN_AUDIO_SECONDS_PER_WORD = 13.0
# Azure neural voices, standard tier, per million characters (azure.microsoft.com
# pricing, 2026-10-09); a suggestion the deployment can change (Q55d).
AZURE_PRICE_PER_MILLION = 15.0

type Sleep = Callable[[float], Awaitable[None]]


class ActiveJobError(Exception):
    """The tenant already has a running or paused job."""


class NoAccentError(Exception):
    """No model in the route reads any of the accents asked for."""


@dataclass(frozen=True)
class Voice:
    connection: str
    model: str
    voice: str


@dataclass(frozen=True)
class Estimate:
    book_id: str
    words: int
    # Accents some model reads, and the voice each would be read in.
    voices: dict[Accent, Voice]
    # Accents asked for that no model reads.
    missing: list[Accent]
    # Word-and-accent pieces of audio: all of them, and those already there.
    pieces: int
    existing: int
    characters: int
    bytes: int
    # None when no price was given.
    cost: float | None
    # What to suggest in the confirm dialog (Q55d, Q55e).
    requests_per_minute: int
    suggested_price: float | None
    # How long one word takes on a model slow enough to matter; None: the pace decides.
    seconds_per_word: float | None = None


def current_voices(tts: TextToSpeech, accents: Sequence[Accent]) -> dict[Accent, Voice]:
    """The first model in the route for each accent and its voice (Q55c)."""
    voices: dict[Accent, Voice] = {}
    for accent in accents:
        candidates = tts.candidates(accent)
        if candidates:
            model, voice = candidates[0]
            voices[accent] = Voice(model.connection, model.model, voice)
    return voices


def _uses_azure(tts: TextToSpeech, voices: dict[Accent, Voice]) -> bool:
    used = {(v.connection, v.model) for v in voices.values()}
    return any(m.kind == "azure_speech" for m in tts.models if (m.connection, m.model) in used)


def max_rate(tts: TextToSpeech, voices: dict[Accent, Voice]) -> int | None:
    """The pace a job can't exceed whatever is asked, or None when the vendor sets none."""
    used = {(v.connection, v.model) for v in voices.values()}
    if any(is_qwen_audio(m) for m in tts.models if (m.connection, m.model) in used):
        return QWEN_AUDIO_MAX_REQUESTS_PER_MINUTE
    return None


def seconds_per_word(tts: TextToSpeech, voices: dict[Accent, Voice]) -> float | None:
    used = {(v.connection, v.model) for v in voices.values()}
    if any(is_qwen_audio(m) for m in tts.models if (m.connection, m.model) in used):
        return QWEN_AUDIO_SECONDS_PER_WORD
    return None


def minutes_needed(pieces: int, requests_per_minute: int, per_word: float | None) -> int:
    """Whole minutes for `pieces` words one at a time: the pace, or the model if slower."""
    each = max(60 / requests_per_minute, per_word or 0)
    return -(-round(pieces * each) // 60)


def suggested_rate(tts: TextToSpeech, voices: dict[Accent, Voice]) -> int:
    if _uses_azure(tts, voices):
        return AZURE_REQUESTS_PER_MINUTE
    return min(OTHER_REQUESTS_PER_MINUTE, max_rate(tts, voices) or OTHER_REQUESTS_PER_MINUTE)


def suggested_price(tts: TextToSpeech, voices: dict[Accent, Voice]) -> float | None:
    return AZURE_PRICE_PER_MILLION if _uses_azure(tts, voices) else None


def word_key(word: str, accent: Accent, voice: Voice) -> str:
    return audio_key(word, accent, voice.voice, WORD_SPEED, voice.connection, voice.model)


async def _book_words(
    session: AsyncSession, book: Book, *, after: int = 0, limit: int | None = None
) -> list[tuple[int, str]]:
    statement = select(Word.id, Word.word).where(book.words(), Word.id > after).order_by(Word.id)
    if limit is not None:
        statement = statement.limit(limit)
    return [(row.id, row.word) for row in await session.execute(statement)]


async def _existing_keys(
    session: AsyncSession, tenant_id: uuid.UUID, keys: Sequence[str]
) -> set[str]:
    found: set[str] = set()
    for start in range(0, len(keys), 1000):
        chunk = keys[start : start + 1000]
        found.update(
            await session.scalars(
                select(TtsAudio.key).where(TtsAudio.tenant_id == tenant_id, TtsAudio.key.in_(chunk))
            )
        )
    return found


async def _bytes_per_word(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    average = await session.scalar(
        select(func.avg(TtsAudio.size)).where(
            TtsAudio.tenant_id == tenant_id, TtsAudio.word_id.is_not(None)
        )
    )
    return round(average) if average is not None else DEFAULT_BYTES_PER_WORD


async def estimate(
    session: AsyncSession,
    tts: TextToSpeech,
    book: Book,
    accents: Sequence[Accent],
    *,
    price_per_million: float | None = None,
) -> Estimate:
    voices = current_voices(tts, accents)
    words = await _book_words(session, book)
    keyed = [
        (word, word_key(word, accent, voice))
        for _, word in words
        for accent, voice in voices.items()
    ]
    existing = await _existing_keys(session, tts.tenant_id, [key for _, key in keyed])
    to_make = [word for word, key in keyed if key not in existing]
    characters = sum(len(word) for word in to_make)
    return Estimate(
        book_id=book.id,
        words=len(words),
        voices=voices,
        missing=[accent for accent in accents if accent not in voices],
        pieces=len(keyed),
        existing=len(keyed) - len(to_make),
        characters=characters,
        bytes=len(to_make) * await _bytes_per_word(session, tts.tenant_id),
        cost=None if price_per_million is None else characters / 1_000_000 * price_per_million,
        requests_per_minute=suggested_rate(tts, voices),
        suggested_price=suggested_price(tts, voices),
        seconds_per_word=seconds_per_word(tts, voices),
    )


async def start(
    session: AsyncSession,
    tts: TextToSpeech,
    book: Book,
    accents: Sequence[Accent],
    *,
    user_id: uuid.UUID | None,
    requests_per_minute: int,
    price_per_million: float | None = None,
    currency: str | None = None,
) -> WordAudioJob:
    """Records a running job; raises NoAccentError or ActiveJobError."""
    voices = current_voices(tts, accents)
    if not voices:
        raise NoAccentError(f"no text-to-speech model reads {', '.join(accents)}")
    words = await session.scalar(select(func.count()).select_from(Word).where(book.words()))
    if (cap := max_rate(tts, voices)) is not None:
        requests_per_minute = min(requests_per_minute, cap)
    job = WordAudioJob(
        tenant_id=tts.tenant_id,
        created_by=user_id,
        book_id=book.id,
        status="running",
        voices={
            accent: {"connection": v.connection, "model": v.model, "voice": v.voice}
            for accent, v in voices.items()
        },
        requests_per_minute=requests_per_minute,
        price_per_million=price_per_million,
        currency=currency,
        total=(words or 0) * len(voices),
    )
    session.add(job)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ActiveJobError("a word audio job is already running or paused") from exc
    return job


def job_voices(job: WordAudioJob) -> dict[Accent, Voice]:
    return {cast(Accent, accent): Voice(**v) for accent, v in job.voices.items()}


@dataclass
class _Tally:
    done: int = 0
    failed: int = 0
    characters: int = 0
    bytes: int = 0


async def _pin(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    word_id: int,
    accent: Accent,
    voice: Voice,
    key: str,
    audio: bytes,
    mime_type: str,
) -> None:
    await session.execute(
        insert(TtsAudio)
        .values(
            tenant_id=tenant_id,
            word_id=word_id,
            key=key,
            language=accent,
            connection_name=voice.connection,
            model=voice.model,
            voice=voice.voice,
            mime_type=mime_type,
            audio=audio,
            size=len(audio),
            pinned=True,
        )
        # Read aloud by a learner in the meantime: keep that audio, pinned.
        .on_conflict_do_update(
            index_elements=["tenant_id", "key"],
            set_={"pinned": True, "word_id": word_id, "user_id": None},
        )
    )


async def _read(
    tts: TextToSpeech, word: str, accent: Accent, sleep: Sleep
) -> tuple[bytes, str] | None:
    """The word's audio, or None when it failed; retries after a 429."""
    for backoff in (*RATE_LIMIT_BACKOFF, None):
        try:
            speech = await tts.synthesize(word, language=accent, speed=WORD_SPEED, background=True)
        except SpeechSynthesisError as exc:
            cause = exc.__cause__
            if backoff is not None and isinstance(cause, EndpointError) and cause.status == 429:
                await sleep(backoff)
                continue
            # The class name only: a vendor's message can echo the request (Q64v).
            logger.warning(
                "word audio for %r (%s) failed: %s",
                word,
                accent,
                type(cause or exc).__name__,
            )
            return None
        return speech.audio, speech.mime_type
    return None


async def run_batch(
    session: AsyncSession,
    job_id: uuid.UUID,
    route: TextToSpeech,
    book: Book,
    *,
    batch_size: int = BATCH_SIZE,
    sleep: Sleep = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Works through the next batch of the job's words; True while there is more to do
    and the job is still running. Progress is saved after each word, and a pause or
    cancel made meanwhile is honoured before the next one."""
    job = await session.get(WordAudioJob, job_id)
    if job is None or job.status != "running":
        return False
    tenant_id = job.tenant_id
    voices = job_voices(job)
    interval = 60 / job.requests_per_minute
    # One model per accent, as the job started; if the route lost it, pause and say so.
    readers: dict[Accent, TextToSpeech] = {}
    for accent, voice in voices.items():
        model = next(
            (m for m in route.models if (m.connection, m.model) == (voice.connection, voice.model)),
            None,
        )
        if model is None:
            await pause(session, job_id, f"model {voice.connection}:{voice.model} left the route")
            return False
        readers[accent] = TextToSpeech(
            tenant_id,
            (model,),
            {f"{voice.connection}:{voice.model}": {accent: voice.voice}},
            task=USAGE_TASK,
        )

    words = await _book_words(session, book, after=job.cursor, limit=batch_size)
    if not words:
        await session.execute(
            update(WordAudioJob)
            .where(WordAudioJob.id == job_id, WordAudioJob.status == "running")
            .values(status="done", finished_at=datetime.now(UTC))
        )
        await session.commit()
        return False

    failures_in_a_row = 0
    for word_id, word in words:
        tally = _Tally()
        keys = {accent: word_key(word, accent, voice) for accent, voice in voices.items()}
        existing = await _existing_keys(session, tenant_id, list(keys.values()))
        for accent, voice in voices.items():
            key = keys[accent]
            if key in existing:
                await session.execute(
                    update(TtsAudio)
                    .where(TtsAudio.tenant_id == tenant_id, TtsAudio.key == key)
                    .values(pinned=True, word_id=word_id, user_id=None)
                )
                tally.done += 1
                continue
            tally.characters += len(word)
            started = clock()
            result = await _read(readers[accent], word, accent, sleep)
            await sleep(max(0.0, interval - (clock() - started)))
            if result is None:
                tally.failed += 1
                failures_in_a_row += 1
                continue
            failures_in_a_row = 0
            audio, mime_type = result
            await _pin(session, tenant_id, word_id, accent, voice, key, audio, mime_type)
            tally.done += 1
            tally.bytes += len(audio)
        status = await session.scalar(
            update(WordAudioJob)
            .where(WordAudioJob.id == job_id)
            .values(
                done=WordAudioJob.done + tally.done,
                failed=WordAudioJob.failed + tally.failed,
                characters=WordAudioJob.characters + tally.characters,
                bytes=WordAudioJob.bytes + tally.bytes,
                cursor=word_id,
            )
            .returning(WordAudioJob.status)
        )
        await session.commit()
        if failures_in_a_row >= FAILURES_BEFORE_PAUSE:
            await pause(session, job_id, f"{failures_in_a_row} words in a row failed")
            return False
        if status != "running":
            return False
    return True


async def pause(session: AsyncSession, job_id: uuid.UUID, error: str) -> None:
    await session.execute(
        update(WordAudioJob)
        .where(WordAudioJob.id == job_id, WordAudioJob.status == "running")
        .values(status="paused", error=error[:300])
    )
    await session.commit()


async def set_status(
    session: AsyncSession, tenant_id: uuid.UUID, action: str
) -> WordAudioJob | None:
    """Pause, resume or cancel the tenant's active job; None when there is none to."""
    moves: dict[str, tuple[str, str]] = {
        "pause": ("running", "paused"),
        "resume": ("paused", "running"),
        "cancel": ("", "cancelled"),
    }
    before, after = moves[action]
    values: dict[str, Any] = {"status": after}
    if action == "resume":
        values["error"] = None
    if action == "cancel":
        values["finished_at"] = datetime.now(UTC)
    allowed = [before] if before else ["running", "paused"]
    job = await session.scalar(
        update(WordAudioJob)
        .where(WordAudioJob.tenant_id == tenant_id, WordAudioJob.status.in_(allowed))
        .values(**values)
        .returning(WordAudioJob)
    )
    await session.commit()
    return job


@dataclass(frozen=True)
class BookAudio:
    book_id: str
    words: int
    # Words with audio in the current voice, per accent.
    made: dict[Accent, int]


@dataclass(frozen=True)
class Stored:
    books: list[BookAudio]
    # All the tenant's word audio, and the part in a voice no longer current (Q55b).
    count: int
    bytes: int
    old_count: int
    old_bytes: int


def _current(voices: dict[Accent, Voice]) -> ColumnElement[bool]:
    """Word audio in the voice now first in the route for its accent."""
    clauses = [
        and_(
            TtsAudio.language == accent,
            TtsAudio.connection_name == v.connection,
            TtsAudio.model == v.model,
            TtsAudio.voice == v.voice,
        )
        for accent, v in voices.items()
    ]
    return or_(*clauses) if clauses else false()


async def stored(
    session: AsyncSession, tenant_id: uuid.UUID, tts: TextToSpeech | None, books: Sequence[Book]
) -> Stored:
    voices = current_voices(tts, ACCENTS) if tts is not None else {}
    word_audio = and_(TtsAudio.tenant_id == tenant_id, TtsAudio.word_id.is_not(None))
    out: list[BookAudio] = []
    for book in books:
        words = await session.scalar(select(func.count()).select_from(Word).where(book.words()))
        made = dict.fromkeys(ACCENTS, 0)
        rows = await session.execute(
            select(TtsAudio.language, func.count())
            .join(Word, Word.id == TtsAudio.word_id)
            .where(word_audio, _current(voices), book.words())
            .group_by(TtsAudio.language)
        )
        for language, count in rows:
            made[cast(Accent, language)] = count
        out.append(BookAudio(book.id, words or 0, made))
    count, size = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(TtsAudio.size), 0)).where(word_audio)
        )
    ).one()
    old_count, old_size = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(TtsAudio.size), 0)).where(
                word_audio, ~_current(voices)
            )
        )
    ).one()
    return Stored(out, count, size, old_count, old_size)


async def delete_audio(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    book: Book | None = None,
    old: bool = False,
    route: TextToSpeech | None = None,
) -> tuple[int, int]:
    """Delete the tenant's word audio for a book (words other books share go too), or
    that in a voice no longer first in `route`; returns how many rows and bytes."""
    where = [TtsAudio.tenant_id == tenant_id, TtsAudio.word_id.is_not(None)]
    if book is not None:
        where.append(TtsAudio.word_id.in_(select(Word.id).where(book.words())))
    if old:
        voices = current_voices(route, ACCENTS) if route is not None else {}
        where.append(~_current(voices))
    rows = (await session.execute(delete(TtsAudio).where(*where).returning(TtsAudio.size))).all()
    await session.commit()
    return len(rows), sum(size for (size,) in rows)


async def latest_job(session: AsyncSession, tenant_id: uuid.UUID) -> WordAudioJob | None:
    return await session.scalar(
        select(WordAudioJob)
        .where(WordAudioJob.tenant_id == tenant_id)
        .order_by(WordAudioJob.created_at.desc())
        .limit(1)
    )
