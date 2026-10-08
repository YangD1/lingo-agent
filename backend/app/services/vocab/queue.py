"""The day's vocabulary queue (ADR 0011 §6, P1 plan §5.2).

Order: due reviews (by due time, no daily cap), then new words from the learner's own
list (auto / manual, oldest first), then new words from the current book (most frequent
first). New words are capped per day; words started earlier today count against it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Exists, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.rules import Rules
from app.db.models import UserCard, UserWordBook, Word
from app.services.vocab.books import get_book
from app.services.vocab.scheduler import day_bounds

# Reviews returned per request; the rest are counted, and come on the next request.
REVIEW_PAGE = 100


@dataclass(frozen=True, slots=True)
class QueueItem:
    word: Word
    # None for a book word not started yet.
    card: UserCard | None


@dataclass(frozen=True, slots=True)
class DailyQueue:
    reviews: list[QueueItem]
    new: list[QueueItem]
    # All reviews due now (may exceed len(reviews)).
    reviews_due: int
    new_limit: int
    # New words started today (first reviewed), including before this request.
    new_started: int
    book_id: str | None


def _due(user_id: uuid.UUID, ahead: datetime) -> tuple[ColumnElement[bool], ...]:
    return (UserCard.user_id == user_id, UserCard.status == "learning", UserCard.due <= ahead)


def _own_new(user_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
    return (
        UserCard.user_id == user_id,
        UserCard.status == "new",
        UserCard.source.in_(("auto", "manual")),
    )


def _has_card(user_id: uuid.UUID) -> Exists:
    return exists().where(UserCard.user_id == user_id, UserCard.word_id == Word.id)


async def _new_allowance(
    session: AsyncSession,
    user_id: uuid.UUID,
    plan: UserWordBook | None,
    *,
    rules: Rules,
    tz: ZoneInfo,
    now: datetime,
) -> tuple[int, int]:
    """The day's new-word limit, and new words started today."""
    start, end = day_bounds(now, tz)
    started = await session.scalar(
        select(func.count())
        .select_from(UserCard)
        .where(
            UserCard.user_id == user_id,
            UserCard.first_reviewed_at >= start,
            UserCard.first_reviewed_at < end,
        )
    )
    return daily_limit(plan, rules), started or 0


async def daily_queue(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> DailyQueue:
    now = now or datetime.now(UTC)
    ahead = now + timedelta(minutes=rules.vocab.learn_ahead_minutes)
    due = _due(user_id, ahead)
    reviews = [
        QueueItem(word=word, card=card)
        for card, word in (
            await session.execute(
                select(UserCard, Word)
                .join(Word, Word.id == UserCard.word_id)
                .where(*due)
                .order_by(UserCard.due, UserCard.id)
                .limit(REVIEW_PAGE)
            )
        ).all()
    ]
    reviews_due = await session.scalar(select(func.count()).select_from(UserCard).where(*due))

    plan = await session.get(UserWordBook, user_id)
    limit, started = await _new_allowance(session, user_id, plan, rules=rules, tz=tz, now=now)
    left = max(0, limit - started)

    book = get_book(plan.book_id) if plan else None
    return DailyQueue(
        reviews=reviews,
        new=await next_new(session, user_id, plan, left),
        reviews_due=reviews_due or 0,
        new_limit=limit,
        new_started=started,
        book_id=book.id if book else None,
    )


async def next_new(
    session: AsyncSession, user_id: uuid.UUID, plan: UserWordBook | None, n: int
) -> list[QueueItem]:
    """The next `n` new words in queue order: the learner's own, then the book's."""
    new: list[QueueItem] = []
    if n <= 0:
        return new
    own = await session.execute(
        select(UserCard, Word)
        .join(Word, Word.id == UserCard.word_id)
        .where(*_own_new(user_id))
        .order_by(UserCard.created_at, UserCard.id)
        .limit(n)
    )
    new = [QueueItem(word=word, card=card) for card, word in own.all()]
    book = get_book(plan.book_id) if plan else None
    if book and len(new) < n:
        fresh = await session.scalars(
            select(Word)
            .where(book.words(), ~_has_card(user_id))
            .order_by(Word.frq.asc().nulls_last(), Word.bnc.asc().nulls_last(), Word.id)
            .limit(n - len(new))
        )
        new += [QueueItem(word=word, card=None) for word in fresh]
    return new


def daily_limit(plan: UserWordBook | None, rules: Rules) -> int:
    return plan.daily_new if plan and plan.daily_new is not None else rules.vocab.daily_new


@dataclass(frozen=True, slots=True)
class TodayCounts:
    reviews_due: int
    # New words still to learn today: the rest of the limit, if that many are left.
    new_left: int
    new_limit: int
    new_started: int


async def today_counts(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> TodayCounts:
    """How much of `daily_queue` is waiting, without loading it."""
    now = now or datetime.now(UTC)
    ahead = now + timedelta(minutes=rules.vocab.learn_ahead_minutes)
    reviews_due = await session.scalar(
        select(func.count()).select_from(UserCard).where(*_due(user_id, ahead))
    )
    plan = await session.get(UserWordBook, user_id)
    limit, started = await _new_allowance(session, user_id, plan, rules=rules, tz=tz, now=now)
    left = max(0, limit - started)
    if left:
        own = await session.scalar(
            select(func.count()).select_from(UserCard).where(*_own_new(user_id))
        )
        available = own or 0
        book = get_book(plan.book_id) if plan else None
        if book and available < left:
            fresh = await session.scalar(
                select(func.count()).select_from(
                    select(Word.id)
                    .where(book.words(), ~_has_card(user_id))
                    .limit(left - available)
                    .subquery()
                )
            )
            available += fresh or 0
        left = min(left, available)
    return TodayCounts(
        reviews_due=reviews_due or 0, new_left=left, new_limit=limit, new_started=started
    )
