"""The day's vocabulary queue (ADR 0011 §6)."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.rules import get_rules
from app.db.models import User, UserCard, UserWordBook, Word
from app.services.vocab.queue import QueueItem, daily_queue
from app.services.vocab.scheduler import review

RULES = get_rules()
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
UTC_ZONE = ZoneInfo("UTC")


async def setup(
    session: AsyncSession, book: str | None = "cet4", daily_new: int | None = None
) -> tuple[uuid.UUID, dict[str, int]]:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    # cet4 words by frequency; "rare" has no rank; "gre1" is in another book.
    words = {
        name: Word(word=name, translation="释义", tags=tags, frq=frq)
        for name, tags, frq in [
            ("common", ["cet4"], 100),
            ("middle", ["cet4"], 2000),
            ("rare", ["cet4"], None),
            ("less", ["cet4"], 5000),
            ("gre1", ["gre"], 50),
            ("mine", [], 9000),
        ]
    }
    session.add_all(words.values())
    await session.flush()
    if book:
        session.add(UserWordBook(user_id=user.id, book_id=book, daily_new=daily_new))
    await session.flush()
    return user.id, {name: w.id for name, w in words.items()}


def names(items: list[QueueItem]) -> list[str]:
    return [item.word.word for item in items]


async def test_book_words_by_frequency_after_the_learners_own(db_session: AsyncSession) -> None:
    user_id, ids = await setup(db_session)
    db_session.add(UserCard(user_id=user_id, word_id=ids["mine"], source="manual", status="new"))
    db_session.add(UserCard(user_id=user_id, word_id=ids["middle"], source="book", status="known"))
    await db_session.flush()

    queue = await daily_queue(db_session, user_id, rules=RULES, tz=UTC_ZONE, now=NOW)

    assert queue.reviews == [] and queue.reviews_due == 0
    # Own list first; then the book, most frequent first, known words skipped,
    # unranked last, other books' words never.
    assert names(queue.new) == ["mine", "common", "less", "rare"]
    assert queue.new[0].card is not None and queue.new[1].card is None
    assert (queue.new_limit, queue.new_started, queue.book_id) == (15, 0, "cet4")


async def test_words_started_today_use_up_the_daily_limit(db_session: AsyncSession) -> None:
    user_id, ids = await setup(db_session, daily_new=2)
    shanghai = ZoneInfo("Asia/Shanghai")
    # 01:00 today in Shanghai, still yesterday in UTC.
    early = datetime(2026, 9, 28, 17, 0, tzinfo=UTC)
    await review(db_session, user_id, word_id=ids["less"], rating=3, rules=RULES, now=early)
    await review(db_session, user_id, word_id=ids["common"], rating=3, rules=RULES, now=NOW)

    queue = await daily_queue(db_session, user_id, rules=RULES, tz=UTC_ZONE, now=NOW)
    assert (queue.new_limit, queue.new_started) == (2, 1)
    assert names(queue.new) == ["middle"]

    # In Shanghai both were started today: nothing new is left.
    queue = await daily_queue(db_session, user_id, rules=RULES, tz=shanghai, now=NOW)
    assert queue.new_started == 2 and queue.new == []


async def test_reviews_due_now_or_within_the_learning_window(db_session: AsyncSession) -> None:
    user_id, ids = await setup(db_session, book=None)
    window = timedelta(minutes=RULES.vocab.learn_ahead_minutes)
    for name, due in [
        ("middle", NOW - timedelta(days=1)),
        ("common", NOW + window - timedelta(minutes=1)),
        ("less", NOW + window + timedelta(minutes=1)),
    ]:
        db_session.add(
            UserCard(
                user_id=user_id,
                word_id=ids[name],
                source="book",
                status="learning",
                state=2,
                due=due,
            )
        )
    db_session.add(
        UserCard(user_id=user_id, word_id=ids["rare"], source="book", status="suspended", due=NOW)
    )
    await db_session.flush()

    queue = await daily_queue(db_session, user_id, rules=RULES, tz=UTC_ZONE, now=NOW)
    assert names(queue.reviews) == ["middle", "common"]
    assert queue.reviews_due == 2
    # No book chosen: only the learner's own list (empty here).
    assert queue.new == [] and queue.book_id is None
