"""Reviewing words: cards, logs and scheduling (ADR 0011)."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.rules import get_rules
from app.db.models import ReviewLog, User, UserCard, UserProfile, Word
from app.services.vocab.scheduler import WordNotFoundError, learner_zone, review

RULES = get_rules()
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


async def learner_and_words(session: AsyncSession, *words: str) -> tuple[uuid.UUID, list[int]]:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    rows = [Word(word=w, translation=f"{w} 的释义") for w in words]
    session.add_all([user, *rows])
    await session.flush()
    return user.id, [w.id for w in rows]


async def test_first_review_creates_the_card_later_ones_reschedule_it(
    db_session: AsyncSession,
) -> None:
    user_id, [word_id] = await learner_and_words(db_session, "abandon")

    card = await review(db_session, user_id, word_id=word_id, rating=3, rules=RULES, now=NOW)
    assert (card.source, card.status, card.state) == ("book", "learning", 1)
    assert card.first_reviewed_at == NOW and card.due is not None and card.due > NOW
    first_due = card.due

    later = NOW + timedelta(minutes=10)
    card = await review(
        db_session, user_id, word_id=word_id, rating=4, rules=RULES, now=later, duration_ms=2300
    )
    await db_session.commit()
    assert card.first_reviewed_at == NOW  # still the day it was started
    assert card.last_review == later and card.due is not None and card.due > first_due
    assert card.state == 2  # "easy" graduates it to review

    logs = (await db_session.scalars(select(ReviewLog).order_by(ReviewLog.id))).all()
    assert [(log.rating, log.review_duration_ms) for log in logs] == [(3, None), (4, 2300)]
    assert logs[0].card_before == {"status": "new"}
    assert logs[1].card_before["state"] == 1 and logs[1].card_after["state"] == 2
    assert logs[1].card_after["status"] == "learning"
    assert (await db_session.scalars(select(UserCard))).all() == [card]


async def test_a_known_word_reviewed_again_is_learned(db_session: AsyncSession) -> None:
    user_id, [word_id] = await learner_and_words(db_session, "the")
    db_session.add(UserCard(user_id=user_id, word_id=word_id, source="book", status="known"))
    await db_session.flush()
    card = await review(db_session, user_id, word_id=word_id, rating=1, rules=RULES, now=NOW)
    assert card.status == "learning" and card.source == "book"


async def test_unknown_word(db_session: AsyncSession) -> None:
    user_id, _ = await learner_and_words(db_session)
    with pytest.raises(WordNotFoundError):
        await review(db_session, user_id, word_id=999_999, rating=3, rules=RULES)


async def test_time_zone_profile_then_browser_then_utc(db_session: AsyncSession) -> None:
    user_id, _ = await learner_and_words(db_session)
    assert await learner_zone(db_session, user_id) == ZoneInfo("UTC")
    assert await learner_zone(db_session, user_id, "Asia/Tokyo") == ZoneInfo("Asia/Tokyo")
    assert await learner_zone(db_session, user_id, "Not/AZone") == ZoneInfo("UTC")
    db_session.add(UserProfile(user_id=user_id, timezone="Asia/Shanghai"))
    await db_session.flush()
    assert await learner_zone(db_session, user_id, "Asia/Tokyo") == ZoneInfo("Asia/Shanghai")
