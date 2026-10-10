"""Word pronunciations generated ahead of time, for owners and admins (ADR 0028 §4).

The settings page estimates a book, starts a job after the deployment confirms the
cost, polls its progress, pauses, resumes or cancels it, and deletes word audio per
book or in voices no longer used (Q55b).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.db.models import Tenant, WordAudioJob
from app.deps import CurrentTenant, CurrentUser, Manager, SessionDep
from app.providers.errors import NoModelConfiguredError
from app.providers.tenant import load_provider_context
from app.providers.tts import TextToSpeech, get_tts
from app.services.speech import word_audio
from app.services.speech.word_audio import Accent, ActiveJobError, NoAccentError
from app.services.speech.worker import WordAudioWorker
from app.services.vocab.books import BOOKS, Book, get_book

router = APIRouter(prefix="/tenant/word-audio", tags=["word-audio"], dependencies=[Manager])

MAX_REQUESTS_PER_MINUTE = 600
MAX_PRICE_PER_MILLION = 10_000.0


def get_worker(request: Request) -> WordAudioWorker:
    worker: WordAudioWorker = request.app.state.word_audio_worker
    return worker


WorkerDep = Annotated[WordAudioWorker, Depends(get_worker)]


class VoiceOut(BaseModel):
    connection: str
    model: str
    voice: str


class JobOut(BaseModel):
    id: uuid.UUID
    book_id: str
    status: str
    voices: dict[Accent, VoiceOut]
    requests_per_minute: int
    price_per_million: float | None
    currency: str | None
    total: int
    done: int
    failed: int
    characters: int
    bytes: int
    # characters x price, when a price was given.
    cost: float | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


def job_out(job: WordAudioJob) -> JobOut:
    price = job.price_per_million
    return JobOut(
        id=job.id,
        book_id=job.book_id,
        status=job.status,
        voices={accent: VoiceOut(**v) for accent, v in job.voices.items()},
        requests_per_minute=job.requests_per_minute,
        price_per_million=price,
        currency=job.currency,
        total=job.total,
        done=job.done,
        failed=job.failed,
        characters=job.characters,
        bytes=job.bytes,
        cost=None if price is None else job.characters / 1_000_000 * price,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


class BookAudioOut(BaseModel):
    book_id: str
    name_zh: str
    name_en: str
    words: int
    made: dict[Accent, int]


class WordAudioOut(BaseModel):
    # The tenant has a read-aloud route that reads some accent.
    available: bool
    # Accent -> the voice a new job would use.
    voices: dict[Accent, VoiceOut]
    # The running or paused job, else the last one.
    job: JobOut | None
    books: list[BookAudioOut]
    count: int
    bytes: int
    old_count: int
    old_bytes: int


async def _route(session: AsyncSession, tenant: Tenant) -> TextToSpeech | None:
    ctx = await load_provider_context(session, tenant.id)
    try:
        return get_tts(ctx)
    except NoModelConfiguredError:
        return None


def _book(book_id: str) -> Book:
    book = get_book(book_id)
    if book is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "unknown_book", "No such word book.")
    return book


def _voices(voices: dict[Accent, word_audio.Voice]) -> dict[Accent, VoiceOut]:
    return {
        a: VoiceOut(connection=v.connection, model=v.model, voice=v.voice)
        for a, v in voices.items()
    }


@router.get("")
async def get_word_audio(tenant: CurrentTenant, session: SessionDep) -> WordAudioOut:
    route = await _route(session, tenant)
    voices = word_audio.current_voices(route, word_audio.ACCENTS) if route else {}
    found = await word_audio.stored(session, tenant.id, route, BOOKS)
    job = await word_audio.latest_job(session, tenant.id)
    return WordAudioOut(
        available=bool(voices),
        voices=_voices(voices),
        job=job_out(job) if job else None,
        books=[
            BookAudioOut(
                book_id=b.book_id,
                name_zh=book.name_zh,
                name_en=book.name_en,
                words=b.words,
                made=b.made,
            )
            for book, b in zip(BOOKS, found.books, strict=True)
        ],
        count=found.count,
        bytes=found.bytes,
        old_count=found.old_count,
        old_bytes=found.old_bytes,
    )


class EstimateOut(BaseModel):
    book_id: str
    words: int
    voices: dict[Accent, VoiceOut]
    missing: list[Accent]
    pieces: int
    existing: int
    characters: int
    bytes: int
    cost: float | None
    requests_per_minute: int
    suggested_price: float | None
    # At `requests_per_minute`, one request per piece left to make.
    minutes: int


def _no_route() -> Exception:
    return api_error(status.HTTP_409_CONFLICT, "no_tts_model", "No read-aloud model is configured.")


@router.get("/estimate")
async def estimate(
    tenant: CurrentTenant,
    session: SessionDep,
    book_id: str,
    accents: Annotated[list[Accent], Query(min_length=1)],
    price_per_million: Annotated[float | None, Query(ge=0, le=MAX_PRICE_PER_MILLION)] = None,
) -> EstimateOut:
    book = _book(book_id)
    route = await _route(session, tenant)
    if route is None:
        raise _no_route()
    found = await word_audio.estimate(
        session, route, book, list(dict.fromkeys(accents)), price_per_million=price_per_million
    )
    to_make = found.pieces - found.existing
    return EstimateOut(
        book_id=found.book_id,
        words=found.words,
        voices=_voices(found.voices),
        missing=found.missing,
        pieces=found.pieces,
        existing=found.existing,
        characters=found.characters,
        bytes=found.bytes,
        cost=found.cost,
        requests_per_minute=found.requests_per_minute,
        suggested_price=found.suggested_price,
        minutes=-(-to_make // found.requests_per_minute),
    )


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: str
    accents: Annotated[list[Accent], Field(min_length=1, max_length=2)]
    requests_per_minute: Annotated[int, Field(ge=1, le=MAX_REQUESTS_PER_MINUTE)]
    price_per_million: Annotated[float | None, Field(ge=0, le=MAX_PRICE_PER_MILLION)] = None
    currency: Annotated[str | None, Field(max_length=8)] = None


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def start_job(
    body: StartIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    worker: WorkerDep,
) -> JobOut:
    book = _book(body.book_id)
    route = await _route(session, tenant)
    if route is None:
        raise _no_route()
    try:
        job = await word_audio.start(
            session,
            route,
            book,
            list(dict.fromkeys(body.accents)),
            user_id=user.id,
            requests_per_minute=body.requests_per_minute,
            price_per_million=body.price_per_million,
            currency=(body.currency or "").strip() or None,
        )
    except NoAccentError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT, "no_tts_voice", "No read-aloud voice for these accents."
        ) from exc
    except ActiveJobError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT, "job_active", "A word audio job is already running or paused."
        ) from exc
    worker.submit(job.id)
    return job_out(job)


@router.post("/jobs/current/{action}")
async def change_job(
    action: Literal["pause", "resume", "cancel"],
    tenant: CurrentTenant,
    session: SessionDep,
    worker: WorkerDep,
) -> JobOut:
    job = await word_audio.set_status(session, tenant.id, action)
    if job is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "no_job", f"No word audio job to {action}.")
    if job.status == "running":
        worker.submit(job.id)
    return job_out(job)


class DeletedOut(BaseModel):
    deleted: int
    bytes: int


@router.delete("")
async def delete_word_audio(
    tenant: CurrentTenant,
    session: SessionDep,
    book_id: str | None = None,
    old: bool = False,
) -> DeletedOut:
    """Delete a book's word audio (shared words of other books too), or with `old` the
    audio in voices a new job would no longer use; not while a job is running or paused,
    since it would skip what it already made."""
    if book_id is None and not old:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "nothing_to_delete", "Name a book or old=true."
        )
    book = _book(book_id) if book_id is not None else None
    job = await word_audio.latest_job(session, tenant.id)
    if job is not None and job.status in ("running", "paused"):
        raise api_error(status.HTTP_409_CONFLICT, "job_active", "Cancel the word audio job first.")
    deleted, size = await word_audio.delete_audio(
        session, tenant.id, book=book, old=old, route=await _route(session, tenant)
    )
    return DeletedOut(deleted=deleted, bytes=size)
