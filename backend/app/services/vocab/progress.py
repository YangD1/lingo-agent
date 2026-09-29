"""Word book progress and choosing a book (ADR 0011, P1 plan §6).

Progress is counted, not stored: a book's words are a filter over `words`, and a
learner's cards belong to words, so each book's share of them is one aggregate query.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserCard, UserWordBook, Word
from app.services.vocab.books import BOOKS, Book, get_book


class UnknownBookError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BookProgress:
    book: Book
    total: int
    # The learner's words in the book being learned (reviewed at least once), and
    # marked known.
    learning: int
    known: int


async def book_progress(session: AsyncSession, user_id: uuid.UUID) -> list[BookProgress]:
    """Every book with its size and the learner's progress in it, in `BOOKS` order."""
    totals = (
        await session.execute(
            select(*(func.count().filter(book.words()) for book in BOOKS)).select_from(Word)
        )
    ).one()
    learning = UserCard.status == "learning"
    known = UserCard.status == "known"
    mine = (
        await session.execute(
            select(
                *(
                    column
                    for book in BOOKS
                    for column in (
                        func.count().filter(book.words(), learning),
                        func.count().filter(book.words(), known),
                    )
                )
            )
            .select_from(UserCard)
            .join(Word, Word.id == UserCard.word_id)
            .where(UserCard.user_id == user_id)
        )
    ).one()
    return [
        BookProgress(book=book, total=totals[i], learning=mine[2 * i], known=mine[2 * i + 1])
        for i, book in enumerate(BOOKS)
    ]


async def choose_book(
    session: AsyncSession, user_id: uuid.UUID, *, book_id: str, daily_new: int | None
) -> UserWordBook:
    """Set the learner's book and daily new words (None = the default); commits.

    Switching books keeps every card; only the screening position, which is a place
    in the old book's order, starts over.
    """
    if get_book(book_id) is None:
        raise UnknownBookError(book_id)
    await session.execute(
        insert(UserWordBook)
        .values(user_id=user_id, book_id=book_id, daily_new=daily_new)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    plan = await session.scalar(
        select(UserWordBook)
        .where(UserWordBook.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert plan is not None
    if plan.book_id != book_id:
        plan.book_id = book_id
        plan.screen_offset = 0
    plan.daily_new = daily_new
    await session.commit()
    return plan


async def current(session: AsyncSession, user_id: uuid.UUID) -> UserWordBook | None:
    """The learner's book and settings; None until a book is chosen."""
    return await session.get(UserWordBook, user_id)
