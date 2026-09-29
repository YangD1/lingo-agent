"""The day's vocabulary queue (ADR 0011 §6, P1 plan §5.2).

Order: due reviews (by due time, no daily cap), then new words from the learner's own
list (auto / manual, oldest first), then new words from the current book (most frequent
first). New words are capped per day; words started earlier today count against it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
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
    due = (UserCard.user_id == user_id, UserCard.status == "learning", UserCard.due <= ahead)
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
    plan = await session.get(UserWordBook, user_id)
    limit = plan.daily_new if plan and plan.daily_new is not None else rules.vocab.daily_new
    left = max(0, limit - (started or 0))

    new: list[QueueItem] = []
    if left:
        own = await session.execute(
            select(UserCard, Word)
            .join(Word, Word.id == UserCard.word_id)
            .where(
                UserCard.user_id == user_id,
                UserCard.status == "new",
                UserCard.source.in_(("auto", "manual")),
            )
            .order_by(UserCard.created_at, UserCard.id)
            .limit(left)
        )
        new = [QueueItem(word=word, card=card) for card, word in own.all()]
    book = get_book(plan.book_id) if plan else None
    if book and len(new) < left:
        has_card = exists().where(UserCard.user_id == user_id, UserCard.word_id == Word.id)
        fresh = await session.scalars(
            select(Word)
            .where(book.words(), ~has_card)
            .order_by(Word.frq.asc().nulls_last(), Word.bnc.asc().nulls_last(), Word.id)
            .limit(left - len(new))
        )
        new += [QueueItem(word=word, card=None) for word in fresh]

    return DailyQueue(
        reviews=reviews,
        new=new,
        reviews_due=reviews_due or 0,
        new_limit=limit,
        new_started=started or 0,
        book_id=book.id if book else None,
    )
