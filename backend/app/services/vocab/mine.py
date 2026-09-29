"""The learner's own word list (生词本): words they or the tutor added (ADR 0011).

These are cards with source `manual` or `auto`; they come before book words in the
daily queue. Removing one really deletes the card and its review history (user's
choice, task 12): adding the word again starts it from scratch.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserCard, Word

OWN_SOURCES = ("auto", "manual")
SUGGESTIONS = 10

type MatchKind = Literal["exact", "case", "lemma"]


@dataclass(frozen=True, slots=True)
class Match:
    word: Word
    kind: MatchKind


BY_FREQUENCY = (Word.frq.asc().nulls_last(), Word.bnc.asc().nulls_last(), Word.id)


def _escape_like(text: str) -> str:
    return re.sub(r"([\\%_])", r"\\\1", text)


async def lookup(session: AsyncSession, text: str) -> Match | None:
    """The dictionary entry for what the learner typed.

    Exact spelling first, then ignoring case, then an inflected form turned back into
    its lemma through ECDICT's `exchange` ("went" -> "go"; forms like "went" have no
    entry of their own). Ties go to the more frequent word.
    """
    text = text.strip()
    if not text:
        return None
    word = await session.scalar(select(Word).where(Word.word == text))
    if word is not None:
        return Match(word, "exact")
    word = await session.scalar(
        select(Word).where(func.lower(Word.word) == text.lower()).order_by(*BY_FREQUENCY).limit(1)
    )
    if word is not None:
        return Match(word, "case")
    # "p:went/d:gone/3:goes": any inflection but 0 (the lemma) and 1 (the form's kinds).
    form = re.escape(text.lower())
    word = await session.scalar(
        select(Word)
        .where(Word.exchange.regexp_match(f"(^|/)[^01/]:{form}(/|$)", flags="i"))
        .order_by(*BY_FREQUENCY)
        .limit(1)
    )
    return Match(word, "lemma") if word is not None else None


async def suggest(session: AsyncSession, prefix: str) -> list[Word]:
    """Words starting with `prefix` (any case), most frequent first."""
    prefix = prefix.strip()
    if not prefix:
        return []
    return list(
        await session.scalars(
            select(Word)
            .where(Word.word.ilike(f"{_escape_like(prefix)}%", escape="\\"))
            .order_by(*BY_FREQUENCY)
            .limit(SUGGESTIONS)
        )
    )


@dataclass(frozen=True, slots=True)
class Added:
    card: UserCard
    # False when the word was already on the list.
    added: bool


async def add(
    session: AsyncSession,
    user_id: uuid.UUID,
    word_id: int,
    *,
    source: Literal["auto", "manual"] = "manual",
) -> Added:
    """Put a word on the learner's list; commits.

    A book word already met joins the list too: being learned, it keeps its schedule;
    marked known, it becomes new again, since the learner wants to learn it after all.
    """
    inserted = await session.scalar(
        insert(UserCard)
        .values(user_id=user_id, word_id=word_id, source=source, status="new")
        .on_conflict_do_nothing(index_elements=["user_id", "word_id"])
        .returning(UserCard.id)
    )
    card = await session.scalar(
        select(UserCard)
        .where(UserCard.user_id == user_id, UserCard.word_id == word_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert card is not None
    added = inserted is not None or card.source == "book"
    if card.source == "book":
        card.source = source
        if card.status in ("known", "suspended"):
            card.status = "new" if card.state is None else "learning"
    await session.commit()
    return Added(card=card, added=added)


@dataclass(frozen=True, slots=True)
class OwnWord:
    card: UserCard
    word: Word


async def list_own(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[OwnWord], int]:
    """The learner's list, newest first, and its full length."""
    own = (UserCard.user_id == user_id, UserCard.source.in_(OWN_SOURCES))
    rows = await session.execute(
        select(UserCard, Word)
        .join(Word, Word.id == UserCard.word_id)
        .where(*own)
        .order_by(UserCard.created_at.desc(), UserCard.id.desc())
        .limit(limit)
        .offset(offset)
    )
    total = await session.scalar(select(func.count()).select_from(UserCard).where(*own))
    return [OwnWord(card=card, word=word) for card, word in rows.all()], total or 0


async def remove(session: AsyncSession, user_id: uuid.UUID, word_id: int) -> bool:
    """Delete a word's card from the list, with its review history; commits."""
    deleted = await session.scalar(
        delete(UserCard)
        .where(
            UserCard.user_id == user_id,
            UserCard.word_id == word_id,
            UserCard.source.in_(OWN_SOURCES),
        )
        .returning(UserCard.id)
    )
    await session.commit()
    return deleted is not None
