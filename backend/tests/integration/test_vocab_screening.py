"""Known-word screening (ADR 0011 §5)."""

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.rules import Rules, ScreeningRules, get_rules
from app.db.models import User, UserCard, UserWordBook, Word
from app.services.vocab.queue import daily_queue
from app.services.vocab.screening import (
    NoBookError,
    NotInBatchError,
    next_batch,
    spread,
    submit,
)


def small_rules() -> Rules:
    rules = get_rules()
    screening = ScreeningRules(batch_size=3, window=6, skip_ratio=0.8)
    return rules.model_copy(
        update={"vocab": rules.vocab.model_copy(update={"screening": screening})}
    )


RULES = small_rules()


async def setup(session: AsyncSession) -> tuple[uuid.UUID, dict[int, int]]:
    """A cet4 book of 20 words ranked 1..20, plus a word from another book."""
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    words = [
        Word(word=f"w{rank:02d}", translation="释义", tags=["cet4"], frq=rank)
        for rank in range(1, 21)
    ]
    session.add_all([user, *words, Word(word="other", translation="释义", tags=["gre"], frq=1)])
    await session.flush()
    session.add(UserWordBook(user_id=user.id, book_id="cet4"))
    await session.flush()
    return user.id, {w.frq: w.id for w in words if w.frq is not None}


def ranks(words: list[Word]) -> list[int | None]:
    return [w.frq for w in words]


def test_spread() -> None:
    assert spread(list(range(10)), 3) == [0, 3, 6]
    assert spread([1, 2], 3) == [1, 2]


async def test_batches_move_through_the_book_and_skip_when_mostly_known(
    db_session: AsyncSession,
) -> None:
    user_id, ids = await setup(db_session)

    batch = await next_batch(db_session, user_id, rules=RULES)
    assert ranks(batch) == [1, 3, 5]  # spread over the first 6
    result = await submit(
        db_session, user_id, shown=[w.id for w in batch], known=[ids[1]], rules=RULES
    )
    assert (result.known, result.shown, result.skipped_ahead) == (1, 3, False)

    # Next batch starts after the last word shown; unticked words are not shown again.
    batch = await next_batch(db_session, user_id, rules=RULES)
    assert ranks(batch) == [6, 8, 10]
    result = await submit(
        db_session, user_id, shown=[w.id for w in batch], known=[w.id for w in batch], rules=RULES
    )
    assert result.skipped_ahead

    # All known: one more window (6 words) is skipped.
    batch = await next_batch(db_session, user_id, rules=RULES)
    assert ranks(batch) == [17, 18, 19]
    await submit(db_session, user_id, shown=[w.id for w in batch], known=[], rules=RULES)
    assert ranks(await next_batch(db_session, user_id, rules=RULES)) == [20]

    cards = (await db_session.scalars(select(UserCard))).all()
    assert sorted(c.word_id for c in cards) == sorted(ids[r] for r in (1, 6, 8, 10))
    assert {(c.status, c.source) for c in cards} == {("known", "book")}
    # Known words stay out of review; unticked ones come up as new words.
    queue = await daily_queue(db_session, user_id, rules=RULES, tz=ZoneInfo("UTC"))
    assert ranks([item.word for item in queue.new])[:3] == [2, 3, 4]


async def test_own_new_words_turn_known_learning_ones_do_not(db_session: AsyncSession) -> None:
    user_id, ids = await setup(db_session)
    db_session.add_all(
        [
            UserCard(user_id=user_id, word_id=ids[1], source="manual", status="new"),
            UserCard(
                user_id=user_id,
                word_id=ids[3],
                source="book",
                status="learning",
                state=2,
                due=datetime.now(UTC),
            ),
        ]
    )
    await db_session.flush()
    await submit(db_session, user_id, shown=[ids[1], ids[3]], known=[ids[1], ids[3]], rules=RULES)
    cards = {c.word_id: c.status for c in (await db_session.scalars(select(UserCard))).all()}
    assert cards == {ids[1]: "known", ids[3]: "learning"}


async def test_bad_submissions(db_session: AsyncSession) -> None:
    user_id, ids = await setup(db_session)
    other = await db_session.scalar(select(Word.id).where(Word.word == "other"))
    assert other is not None
    with pytest.raises(NotInBatchError):
        await submit(db_session, user_id, shown=[ids[1]], known=[ids[2]], rules=RULES)
    with pytest.raises(NotInBatchError):  # not in the book
        await submit(db_session, user_id, shown=[other], known=[], rules=RULES)
    stranger = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    db_session.add(stranger)
    await db_session.flush()
    with pytest.raises(NoBookError):
        await next_batch(db_session, stranger.id, rules=RULES)
