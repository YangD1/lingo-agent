"""Marking a word book's common words known from the placement result (P1 plan §6.2, Q15c).

The vocabulary test gives V, the rank at which the learner knows half the words. Up to
the rank where they know a word with probability `mark_known_p`, the book's words are
offered to be marked known in one go; nothing happens until the learner confirms.
Those cards carry `source = placement`, so the whole batch can be taken back.

Known cards are skipped by screening and the daily queue alike, so `screen_offset` is
left alone and undoing needs nothing but deleting the cards.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.adaptive.placement.vocab_size import rank_at
from app.adaptive.rules import Rules
from app.db.models import PlacementSession, UserCard, UserWordBook
from app.db.models import Word as WordRow
from app.services.vocab.books import get_book

type Unavailable = Literal["no_placement", "unreliable", "no_book"]


@dataclass(frozen=True, slots=True)
class Suggestion:
    # Why nothing can be offered; None when `count` words can be marked.
    unavailable: Unavailable | None
    book_id: str | None
    # Book words ranked this common or more, without a card yet.
    up_to_rank: int | None
    count: int
    # Cards marked known this way that are still known (what undo would remove).
    marked: int


def _placement_known(user_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
    return (
        UserCard.user_id == user_id,
        UserCard.source == "placement",
        UserCard.status == "known",
    )


async def _marked(session: AsyncSession, user_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count()).select_from(UserCard).where(*_placement_known(user_id))
    )
    return count or 0


async def _latest_vocab(session: AsyncSession, user_id: uuid.UUID) -> dict[str, object] | None:
    result: dict[str, object] | None = await session.scalar(
        select(PlacementSession.result)
        .where(PlacementSession.user_id == user_id, PlacementSession.status == "done")
        .order_by(PlacementSession.finished_at.desc())
        .limit(1)
    )
    vocab = result.get("vocab") if result else None
    return vocab if isinstance(vocab, dict) else None


async def _plan(
    session: AsyncSession, user_id: uuid.UUID, rules: Rules
) -> tuple[Suggestion, Select[int] | None]:
    """The suggestion and, when there is one, the query for its word ids."""
    marked = await _marked(session, user_id)
    vocab = await _latest_vocab(session, user_id)
    if vocab is None:
        return Suggestion("no_placement", None, None, 0, marked), None
    if not vocab.get("reliable"):
        return Suggestion("unreliable", None, None, 0, marked), None
    plan = await session.get(UserWordBook, user_id)
    book = get_book(plan.book_id) if plan else None
    if book is None:
        return Suggestion("no_book", None, None, 0, marked), None
    half_known = float(vocab["half_known_rank"])  # type: ignore[arg-type]
    up_to = rank_at(max(half_known, 1.0), rules.placement.vocab.mark_known_p, rules.placement.vocab)
    has_card = exists().where(UserCard.user_id == user_id, UserCard.word_id == WordRow.id)
    ids = select(WordRow.id).where(book.words(), WordRow.frq.between(1, up_to), ~has_card)
    count = await session.scalar(select(func.count()).select_from(ids.subquery())) or 0
    return Suggestion(None, book.id, up_to, count, marked), ids


async def suggestion(session: AsyncSession, user_id: uuid.UUID, *, rules: Rules) -> Suggestion:
    return (await _plan(session, user_id, rules))[0]


async def mark_known(session: AsyncSession, user_id: uuid.UUID, *, rules: Rules) -> int:
    """Mark the suggested words known; commits. Returns how many were marked."""
    _, ids = await _plan(session, user_id, rules)
    if ids is None:
        return 0
    word_ids = list(await session.scalars(ids))
    if not word_ids:
        return 0
    rows = (
        await session.scalars(
            insert(UserCard)
            .values(
                [
                    {"user_id": user_id, "word_id": w, "source": "placement", "status": "known"}
                    for w in word_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["user_id", "word_id"])
            .returning(UserCard.id)
        )
    ).all()
    await session.commit()
    return len(rows)


async def undo(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Delete the known cards made by `mark_known`; commits. Returns how many."""
    removed = await session.scalars(
        delete(UserCard).where(*_placement_known(user_id)).returning(UserCard.id)
    )
    count = len(removed.all())
    await session.commit()
    return count
