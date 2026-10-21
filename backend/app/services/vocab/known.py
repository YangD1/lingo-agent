"""Words the learner marked known from a review card, and taking them back (task 120).

Marking keeps the card's FSRS state, so a word added back picks up where it left off:
a word reviewed before is due at once; one never reviewed is new again. A book or
placement word never reviewed loses its card instead, since the queue finds new book
words by their having no card; it then comes in book order like any unseen word.

The known list holds every known card, however it was marked: on a card, by
screening, from the placement test, or by the learner's own list.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserCard, Word
from app.services.vocab.mine import OWN_SOURCES, escape_like


class WordNotFoundError(Exception):
    """No such word in the dictionary."""


async def _locked(session: AsyncSession, user_id: uuid.UUID, word_id: int) -> UserCard | None:
    return await session.scalar(
        select(UserCard)
        .where(UserCard.user_id == user_id, UserCard.word_id == word_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def mark(session: AsyncSession, user_id: uuid.UUID, word_id: int) -> UserCard:
    """Mark a word known, making a book card for a word never met; commits.

    Idempotent; the FSRS columns are left as they are.
    """
    if await session.get(Word, word_id) is None:
        raise WordNotFoundError(word_id)
    await session.execute(
        insert(UserCard)
        .values(user_id=user_id, word_id=word_id, source="book", status="known")
        .on_conflict_do_nothing(index_elements=["user_id", "word_id"])
    )
    card = await _locked(session, user_id, word_id)
    assert card is not None
    card.status = "known"
    await session.commit()
    return card


async def unmark(
    session: AsyncSession, user_id: uuid.UUID, word_id: int, *, now: datetime | None = None
) -> UserCard | None:
    """Put a known word back into review; commits. Returns the card, or None when it
    no longer has one.

    Idempotent: a word that is not known is left alone.
    """
    card = await _locked(session, user_id, word_id)
    if card is None or card.status != "known":
        await session.commit()
        return card
    if card.state is not None:
        card.status = "learning"
        card.due = now or datetime.now(UTC)
    elif card.source in OWN_SOURCES:
        card.status = "new"
    else:
        await session.delete(card)
        await session.commit()
        return None
    await session.commit()
    return card


@dataclass(frozen=True, slots=True)
class KnownWord:
    card: UserCard
    word: Word


async def list_known(
    session: AsyncSession, user_id: uuid.UUID, *, q: str = "", limit: int, offset: int
) -> tuple[list[KnownWord], int]:
    """Known words, most recently marked first, and how many match; `q` filters by
    the word's start, ignoring case."""
    where: list[ColumnElement[bool]] = [UserCard.user_id == user_id, UserCard.status == "known"]
    if q := q.strip():
        where.append(Word.word.ilike(f"{escape_like(q)}%", escape="\\"))
    rows = await session.execute(
        select(UserCard, Word)
        .join(Word, Word.id == UserCard.word_id)
        .where(*where)
        .order_by(UserCard.updated_at.desc(), UserCard.id.desc())
        .limit(limit)
        .offset(offset)
    )
    total = await session.scalar(
        select(func.count())
        .select_from(UserCard)
        .join(Word, Word.id == UserCard.word_id)
        .where(*where)
    )
    return [KnownWord(card=card, word=word) for card, word in rows.all()], total or 0
