"""Vocabulary: word books, the daily queue, reviewing, screening and the learner's own
word list (ADR 0011, P1 plan §6). Everything here is the current user's own data."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from app.adaptive.rules import get_rules
from app.api.errors import api_error
from app.db.models import UserCard, Word
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.memory.service import get_profile
from app.providers.errors import NoModelConfiguredError
from app.providers.tenant import load_provider_context
from app.services.vocab import examples, mine, placement_known, progress, screening
from app.services.vocab.mine import MatchKind
from app.services.vocab.queue import QueueItem, daily_queue, today_counts
from app.services.vocab.scheduler import (
    Rating,
    WordNotFoundError,
    learner_zone,
    preview,
    review,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vocab", tags=["vocab"])

# The browser's IANA time zone, used when the profile has none (P1 plan §5.2).
TimeZone = Annotated[str | None, Query(max_length=64)]


class WordOut(BaseModel):
    id: int
    word: str
    phonetic: str | None
    translation: str
    definition: str | None


class CardOut(BaseModel):
    word: WordOut
    # None for a book word never met; the rest mirror `user_cards`.
    source: str | None
    status: str | None
    due: datetime | None
    last_review: datetime | None
    # Seconds until the next review for ratings 1-4 if rated now, for the rating buttons.
    intervals: list[int]


class BookOut(BaseModel):
    id: str
    name_zh: str
    name_en: str
    total: int
    learning: int
    known: int


class TodayOut(BaseModel):
    reviews_due: int
    new_left: int
    new_limit: int
    new_started: int


class VocabOut(BaseModel):
    books: list[BookOut]
    # The current book; None until one is chosen.
    book_id: str | None
    # None = the default, `daily_new_default`.
    daily_new: int | None
    daily_new_default: int
    # A known-word screening batch has been submitted for the current book.
    screened: bool
    today: TodayOut


class BookIn(BaseModel):
    book_id: str = Field(max_length=20)
    daily_new: int | None = Field(default=None, ge=0, le=200)


class QueueOut(BaseModel):
    reviews: list[CardOut]
    new: list[CardOut]
    reviews_due: int
    new_limit: int
    new_started: int
    book_id: str | None


class ReviewIn(BaseModel):
    word_id: int
    rating: Rating
    duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)


class ScreenOut(BaseModel):
    # Empty when every word of the book has been met.
    words: list[WordOut]


class ScreenIn(BaseModel):
    shown: list[int] = Field(max_length=1000)
    known: list[int] = Field(max_length=1000)


class ScreenResultOut(BaseModel):
    known: int
    shown: int
    skipped_ahead: bool


class PlacementKnownOut(BaseModel):
    # Why there is nothing to offer: no finished placement test, an unreliable
    # vocabulary result, or no word book chosen. None when `count` words can be marked.
    unavailable: Literal["no_placement", "unreliable", "no_book"] | None
    book_id: str | None
    # The book's words ranked this common or more, not met yet, are offered.
    up_to_rank: int | None
    count: int
    # Words marked known this way so far (what undo takes back).
    marked: int


class CountOut(BaseModel):
    count: int


class MinePage(BaseModel):
    words: list[CardOut]
    total: int


class AddIn(BaseModel):
    word: str = Field(min_length=1, max_length=100)


class AddedOut(BaseModel):
    card: CardOut
    # How the typed text matched: "lemma" means `card.word` is its base form.
    matched: MatchKind
    # False when the word was already on the list.
    added: bool


class LookupOut(BaseModel):
    word: WordOut
    # "lemma": the looked-up text is an inflection of `word` ("went" -> "go").
    matched: MatchKind
    # On the learner's own word list (生词本).
    on_list: bool


class Sentence(BaseModel):
    en: str
    zh: str


class ExamplesOut(BaseModel):
    sentences: list[Sentence]
    # The level they were written for.
    cefr: str


def _word(word: Word) -> WordOut:
    return WordOut(
        id=word.id,
        word=word.word,
        phonetic=word.phonetic,
        translation=word.translation,
        definition=word.definition,
    )


def _card(word: Word, card: UserCard | None, now: datetime) -> CardOut:
    return CardOut(
        word=_word(word),
        source=card.source if card else None,
        status=card.status if card else None,
        due=card.due if card else None,
        last_review=card.last_review if card else None,
        intervals=preview(card, get_rules(), now),
    )


def _item(item: QueueItem, now: datetime) -> CardOut:
    return _card(item.word, item.card, now)


def _no_book() -> Exception:
    return api_error(status.HTTP_409_CONFLICT, "no_book", "choose a word book first")


@router.get("")
async def get_vocab(user: CurrentUser, session: SessionDep, tz: TimeZone = None) -> VocabOut:
    rules = get_rules()
    books = await progress.book_progress(session, user.id)
    plan = await progress.current(session, user.id)
    today = await today_counts(
        session, user.id, rules=rules, tz=await learner_zone(session, user.id, tz)
    )
    return VocabOut(
        books=[
            BookOut(
                id=p.book.id,
                name_zh=p.book.name_zh,
                name_en=p.book.name_en,
                total=p.total,
                learning=p.learning,
                known=p.known,
            )
            for p in books
        ],
        book_id=plan.book_id if plan else None,
        daily_new=plan.daily_new if plan else None,
        daily_new_default=rules.vocab.daily_new,
        screened=bool(plan and plan.screen_offset),
        today=TodayOut(
            reviews_due=today.reviews_due,
            new_left=today.new_left,
            new_limit=today.new_limit,
            new_started=today.new_started,
        ),
    )


@router.put("/book", status_code=status.HTTP_204_NO_CONTENT)
async def put_book(body: BookIn, user: CurrentUser, session: SessionDep) -> Response:
    try:
        await progress.choose_book(session, user.id, book_id=body.book_id, daily_new=body.daily_new)
    except progress.UnknownBookError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "book_not_found", "unknown word book") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/queue")
async def get_queue(
    user: CurrentUser,
    session: SessionDep,
    tz: TimeZone = None,
    mode: Literal["all", "new"] = "all",
) -> QueueOut:
    """The words to review now, then today's new words. `mode=new` leaves reviews out
    (their count stays); cards still being learned come back within minutes, so the
    client asks again when it runs out."""
    queue = await daily_queue(
        session, user.id, rules=get_rules(), tz=await learner_zone(session, user.id, tz)
    )
    now = datetime.now(UTC)
    return QueueOut(
        reviews=[] if mode == "new" else [_item(i, now) for i in queue.reviews],
        new=[_item(i, now) for i in queue.new],
        reviews_due=queue.reviews_due,
        new_limit=queue.new_limit,
        new_started=queue.new_started,
        book_id=queue.book_id,
    )


@router.post("/reviews")
async def post_review(body: ReviewIn, user: CurrentUser, session: SessionDep) -> CardOut:
    try:
        card = await review(
            session,
            user.id,
            word_id=body.word_id,
            rating=body.rating,
            rules=get_rules(),
            duration_ms=body.duration_ms,
        )
    except WordNotFoundError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "word_not_found", "word not found") from exc
    await session.commit()
    word = await session.get(Word, body.word_id)
    assert word is not None
    return _card(word, card, datetime.now(UTC))


@router.get("/screen")
async def get_screen(user: CurrentUser, session: SessionDep) -> ScreenOut:
    try:
        words = await screening.next_batch(session, user.id, rules=get_rules())
    except screening.NoBookError as exc:
        raise _no_book() from exc
    return ScreenOut(words=[_word(w) for w in words])


@router.post("/screen")
async def post_screen(body: ScreenIn, user: CurrentUser, session: SessionDep) -> ScreenResultOut:
    try:
        result = await screening.submit(
            session, user.id, shown=body.shown, known=body.known, rules=get_rules()
        )
    except screening.NoBookError as exc:
        raise _no_book() from exc
    except screening.NotInBatchError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "not_in_batch",
            "known words must be among the words shown, which must be in the book",
        ) from exc
    return ScreenResultOut(
        known=result.known, shown=result.shown, skipped_ahead=result.skipped_ahead
    )


@router.get("/placement-known")
async def get_placement_known(user: CurrentUser, session: SessionDep) -> PlacementKnownOut:
    """What the last placement test suggests marking known in the current book."""
    offer = await placement_known.suggestion(session, user.id, rules=get_rules())
    return PlacementKnownOut(
        unavailable=offer.unavailable,
        book_id=offer.book_id,
        up_to_rank=offer.up_to_rank,
        count=offer.count,
        marked=offer.marked,
    )


@router.post("/placement-known")
async def post_placement_known(user: CurrentUser, session: SessionDep) -> CountOut:
    """Mark the suggested words known (the learner confirmed); returns how many."""
    return CountOut(count=await placement_known.mark_known(session, user.id, rules=get_rules()))


@router.delete("/placement-known")
async def delete_placement_known(user: CurrentUser, session: SessionDep) -> CountOut:
    """Take back every word marked known from placement; returns how many."""
    return CountOut(count=await placement_known.undo(session, user.id))


@router.get("/words")
async def get_words(
    session: SessionDep,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=100)],
) -> list[WordOut]:
    """Dictionary words starting with `q`, for the add-a-word box."""
    return [_word(w) for w in await mine.suggest(session, q)]


@router.get("/lookup")
async def lookup_word(
    session: SessionDep,
    user: CurrentUser,
    word: Annotated[str, Query(min_length=1, max_length=100)],
) -> LookupOut:
    """The dictionary entry for a word in a tutor message (ADR 0017 §2); no model."""
    match = await mine.lookup(session, word)
    if match is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "word_not_found", "the dictionary has no such word"
        )
    return LookupOut(
        word=_word(match.word),
        matched=match.kind,
        on_list=match.word.id in await mine.on_list(session, user.id, [match.word.id]),
    )


@router.post("/words/{word_id}/examples")
async def post_examples(
    word_id: int, user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> ExamplesOut:
    """Two example sentences at the learner's level, written by a model once per
    tenant, word and level, then cached (ADR 0017 §3)."""
    word = await session.get(Word, word_id)
    if word is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "word_not_found", "no such word")
    profile = await get_profile(session, user.id)
    cefr = (profile.cefr_level if profile else None) or examples.DEFAULT_LEVEL
    ctx = await load_provider_context(session, tenant.id)
    try:
        sentences = await examples.examples(
            session, ctx, word, cefr, {"metadata": {"user_id": str(user.id)}}
        )
    except NoModelConfiguredError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT, exc.code, "No chat model is configured. Add one in Settings."
        ) from exc
    except examples.ExamplesInvalidError as exc:
        raise api_error(
            status.HTTP_502_BAD_GATEWAY,
            "examples_invalid",
            "The model's sentences didn't use the word. Please try again.",
        ) from exc
    except Exception as exc:
        # Details stay in the server log; vendor errors can echo input.
        logger.exception("writing examples for word %s failed", word_id)
        raise api_error(
            status.HTTP_502_BAD_GATEWAY, "llm_unavailable", "The model is unavailable right now."
        ) from exc
    return ExamplesOut(sentences=[Sentence(**s) for s in sentences], cefr=cefr)


@router.get("/mine")
async def get_mine(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MinePage:
    words, total = await mine.list_own(session, user.id, limit=limit, offset=offset)
    return MinePage(words=[_card(w.word, w.card, datetime.now(UTC)) for w in words], total=total)


@router.post("/mine")
async def post_mine(
    body: AddIn, user: CurrentUser, session: SessionDep, response: Response
) -> AddedOut:
    match = await mine.lookup(session, body.word)
    if match is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "word_not_found", "the dictionary has no such word"
        )
    added = await mine.add(session, user.id, match.word.id)
    response.status_code = status.HTTP_201_CREATED if added.added else status.HTTP_200_OK
    return AddedOut(
        card=_card(match.word, added.card, datetime.now(UTC)), matched=match.kind, added=added.added
    )


@router.delete("/mine/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mine(word_id: int, user: CurrentUser, session: SessionDep) -> Response:
    """Remove a word from the list. Really deleted, with its review history."""
    if not await mine.remove(session, user.id, word_id):
        raise api_error(status.HTTP_404_NOT_FOUND, "word_not_found", "word not on your list")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
