"""Known-word screening (ADR 0011 §5, P1 plan §5.2).

The learner is shown a batch of their book's words and ticks the ones they know; those
become `known` cards and never enter review. A batch is spread over a window of
not-yet-seen words in frequency order, so one batch spans common to rarer words; the
next batch starts after it, so no word is shown twice. Words left unticked stay
unseen and come up as new words in review. When most of a batch is known, the next
batch also skips one more window, among rarer words.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Subquery

from app.adaptive.rules import Rules
from app.db.models import UserCard, UserWordBook, Word
from app.services.vocab.books import Book, get_book


class NoBookError(Exception):
    """The learner has not chosen a word book."""


class NotInBatchError(Exception):
    """A word marked known is not among the words shown."""


def _positions(book: Book) -> Subquery:
    """Each book word's 1-based place in frequency order."""
    return (
        select(
            Word.id.label("word_id"),
            func.row_number()
            .over(order_by=(Word.frq.asc().nulls_last(), Word.bnc.asc().nulls_last(), Word.id))
            .label("pos"),
        )
        .where(book.words())
        .subquery()
    )


async def _plan(session: AsyncSession, user_id: uuid.UUID) -> tuple[UserWordBook, Book]:
    plan = await session.get(UserWordBook, user_id)
    book = get_book(plan.book_id) if plan else None
    if plan is None or book is None:
        raise NoBookError(user_id)
    return plan, book


def spread[T](items: list[T], n: int) -> list[T]:
    """n items evenly spaced over `items` (all of them if there are no more than n)."""
    if len(items) <= n:
        return items
    return [items[i * len(items) // n] for i in range(n)]


async def next_batch(session: AsyncSession, user_id: uuid.UUID, *, rules: Rules) -> list[Word]:
    """The next words to screen, most frequent first; empty when the book is done."""
    plan, book = await _plan(session, user_id)
    pos = _positions(book)
    has_card = exists().where(UserCard.user_id == user_id, UserCard.word_id == pos.c.word_id)
    window = await session.scalars(
        select(Word)
        .join(pos, pos.c.word_id == Word.id)
        .where(pos.c.pos > plan.screen_offset, ~has_card)
        .order_by(pos.c.pos)
        .limit(rules.vocab.screening.window)
    )
    return spread(list(window), rules.vocab.screening.batch_size)


@dataclass(frozen=True, slots=True)
class ScreeningResult:
    known: int
    shown: int
    # The next batch skips a window of rarer words.
    skipped_ahead: bool


async def submit(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    shown: Collection[int],
    known: Collection[int],
    rules: Rules,
) -> ScreeningResult:
    """Record a screened batch: `known` words become known cards; commits.

    Words already on the learner's own list turn known too; words already being
    learned are left alone (their schedule knows better).
    """
    plan, book = await _plan(session, user_id)
    shown_ids, known_ids = set(shown), set(known)
    if not known_ids <= shown_ids:
        raise NotInBatchError(sorted(known_ids - shown_ids))
    pos = _positions(book)
    places: dict[int, int] = dict(
        (
            await session.execute(
                select(pos.c.word_id, pos.c.pos).where(pos.c.word_id.in_(shown_ids))
            )
        ).all()
    )
    if set(places) != shown_ids:
        raise NotInBatchError(sorted(shown_ids - set(places)))
    if known_ids:
        await session.execute(
            insert(UserCard)
            .values(
                [
                    {"user_id": user_id, "word_id": word_id, "source": "book", "status": "known"}
                    for word_id in sorted(known_ids)
                ]
            )
            .on_conflict_do_nothing(index_elements=["user_id", "word_id"])
        )
        await session.execute(
            update(UserCard)
            .where(
                UserCard.user_id == user_id,
                UserCard.word_id.in_(known_ids),
                UserCard.status == "new",
            )
            .values(status="known")
        )
    screening = rules.vocab.screening
    skip = bool(shown_ids) and len(known_ids) / len(shown_ids) >= screening.skip_ratio
    if places:
        after = max(places.values()) + (screening.window if skip else 0)
        plan.screen_offset = max(plan.screen_offset, after)
    await session.commit()
    return ScreeningResult(known=len(known_ids), shown=len(shown_ids), skipped_ahead=skip)
