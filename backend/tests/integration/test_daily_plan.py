"""Today's plan in the database (ADR 0027, task 48.2)."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.daily_plan import service
from app.adaptive.daily_plan.algorithm import PlanChoice
from app.adaptive.daily_plan.service import PlanStateError
from app.adaptive.rules import get_rules
from app.db.models import (
    Article,
    ArticleVersion,
    DailyPlan,
    ExerciseSet,
    Feed,
    ReadingSession,
    UserCard,
    UserProfile,
    UserWordBook,
    Word,
    WritingSubmission,
)
from app.services.news.sources import sync_builtin_feeds
from app.services.reading.versions import reading_level
from app.services.vocab.scheduler import review
from tests.integration.test_dashboard import new_user

RULES = get_rules()
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
UTC_ZONE = ZoneInfo("UTC")


async def words(session: AsyncSession, n: int) -> list[int]:
    rows = [
        Word(word=f"w{uuid.uuid4().hex[:10]}", translation="释义", tags=["cet4"]) for _ in range(n)
    ]
    session.add_all(rows)
    await session.flush()
    return [w.id for w in rows]


async def due_cards(session: AsyncSession, user_id: uuid.UUID, n: int) -> list[int]:
    """n words first reviewed two days ago, due again now."""
    ids = await words(session, n)
    for word_id in ids:
        await review(
            session, user_id, word_id=word_id, rating=1, rules=RULES, now=NOW - timedelta(days=2)
        )
    return ids


async def today(session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID) -> DailyPlan:
    return await service.today(session, user_id, tenant_id, rules=RULES, tz=UTC_ZONE, now=NOW)


async def test_drafted_once_a_day_and_then_kept(db_session: AsyncSession) -> None:
    user_id, tenant_id = await new_user(db_session)
    db_session.add(UserProfile(user_id=user_id, interests=[], manual_fields=[], daily_minutes=30))
    db_session.add(UserWordBook(user_id=user_id, book_id="cet4", daily_new=5))
    await due_cards(db_session, user_id, 4)
    await words(db_session, 10)

    plan = await today(db_session, user_id, tenant_id)
    assert plan.status == "proposed" and plan.day.isoformat() == "2026-10-09"
    assert plan.limits["minutes"] == 30
    assert plan.limits["reviews_due"] == 4 and plan.limits["new_left"] == 5
    # A learner with no evidence still has grammar points in their level window.
    assert plan.limits["practice_kc"] is not None
    assert plan.choice == {
        "review": 4,
        "new_words": 5,
        "practice": True,
        "reading": False,
        "writing": False,
    }

    # More words come due later: the numbers stay (Q48e).
    await due_cards(db_session, user_id, 3)
    again = await today(db_session, user_id, tenant_id)
    assert again.id == plan.id and again.choice == plan.choice

    # Tomorrow is a new plan.
    tomorrow = await service.today(
        db_session, user_id, tenant_id, rules=RULES, tz=UTC_ZONE, now=NOW + timedelta(days=1)
    )
    assert tomorrow.id != plan.id


async def test_the_day_is_the_learners(db_session: AsyncSession) -> None:
    user_id, tenant_id = await new_user(db_session)
    late = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
    plan = await service.today(
        db_session, user_id, tenant_id, rules=RULES, tz=ZoneInfo("Asia/Shanghai"), now=late
    )
    assert plan.day.isoformat() == "2026-10-10"


async def test_progress_from_each_modules_records(db_session: AsyncSession) -> None:
    user_id, tenant_id = await new_user(db_session)
    db_session.add(UserWordBook(user_id=user_id, book_id="cet4", daily_new=3))
    old = await due_cards(db_session, user_id, 3)
    await words(db_session, 5)
    plan = await today(db_session, user_id, tenant_id)
    assert plan.choice["review"] == 3 and plan.choice["new_words"] == 3

    async def progress() -> dict[str, tuple[int, int]]:
        v = await service.view(db_session, plan, rules=RULES, tz=UTC_ZONE, now=NOW)
        return {p.item.kind: (p.done, p.target) for p in v.progress}

    assert await progress() == {"review": (0, 3), "practice": (0, 1), "new_words": (0, 3)}

    # Two reviews of old words (one twice) and one new word, which counts only as new.
    await review(db_session, user_id, word_id=old[0], rating=1, rules=RULES, now=NOW)
    await review(db_session, user_id, word_id=old[0], rating=3, rules=RULES, now=NOW)
    await review(db_session, user_id, word_id=old[1], rating=3, rules=RULES, now=NOW)
    fresh = await words(db_session, 1)
    await review(db_session, user_id, word_id=fresh[0], rating=3, rules=RULES, now=NOW)
    # A set finished yesterday does not count; one finished today does.
    db_session.add_all(
        [
            ExerciseSet(
                user_id=user_id,
                origin="practice",
                status="done",
                kc_plan=[],
                finished_at=NOW - timedelta(days=1),
            ),
            ExerciseSet(
                user_id=user_id, origin="practice", status="in_progress", kc_plan=[], started_at=NOW
            ),
        ]
    )
    await db_session.flush()
    assert await progress() == {"review": (3, 3), "practice": (0, 1), "new_words": (1, 3)}

    db_session.add(
        ExerciseSet(user_id=user_id, origin="plan", status="done", kc_plan=[], finished_at=NOW)
    )
    await db_session.flush()
    v = await service.view(db_session, plan, rules=RULES, tz=UTC_ZONE, now=NOW)
    done = {p.item.kind: p.complete for p in v.progress}
    assert done == {"review": True, "practice": True, "new_words": False}
    assert v.minutes == 3 * 0.25 + 8 + 3 * 1.0


async def test_reading_and_writing(db_session: AsyncSession) -> None:
    user_id, tenant_id = await new_user(db_session)
    db_session.add(UserProfile(user_id=user_id, interests=[], manual_fields=[], daily_minutes=60))
    await sync_builtin_feeds(db_session)
    feed = await db_session.scalar(select(Feed).where(Feed.builtin_key.is_not(None)))
    assert feed is not None

    def article(title: str, hours: int) -> Article:
        return Article(
            feed_id=feed.id,
            guid=title,
            url=f"https://example.com/{uuid.uuid4()}",
            title=title,
            published_at=NOW - timedelta(hours=hours),
            body="One.\n\nTwo.",
            summary_only=False,
            license=feed.license,
            word_count=300,
            tags=[],
        )

    newest, rewritten, read = article("newest", 1), article("rewritten", 2), article("read", 0)
    db_session.add_all([newest, rewritten, read])
    await db_session.flush()
    level = await reading_level(db_session, user_id, RULES)
    db_session.add_all(
        [
            ArticleVersion(
                tenant_id=tenant_id, article_id=rewritten.id, level=level, status="ready"
            ),
            ReadingSession(user_id=user_id, article_id=read.id, level=level),
            # Wrote 3 days ago: no essay today (writing_gap_days = 7).
            WritingSubmission(
                user_id=user_id,
                text="x",
                word_count=1,
                status="done",
                created_at=NOW - timedelta(days=3),
            ),
        ]
    )
    await db_session.flush()

    inputs = await service.read_inputs(
        db_session, user_id, tenant_id, rules=RULES, tz=UTC_ZONE, now=NOW
    )
    # Unread, and already rewritten for the learner's level, before the newest.
    assert inputs.article_id == rewritten.id
    assert inputs.days_since_writing == 3

    plan = await today(db_session, user_id, tenant_id)
    assert plan.choice["reading"] is True and plan.choice["writing"] is False

    # The learner switches the essay on when confirming, then writes and reads.
    plan = await service.confirm(
        db_session,
        user_id,
        plan.id,
        rules=RULES,
        tz=UTC_ZONE,
        now=NOW,
        choice=PlanChoice(practice=True, reading=True, writing=True),
    )
    db_session.add(
        WritingSubmission(user_id=user_id, text="y", word_count=1, status="pending", created_at=NOW)
    )
    other = await db_session.scalar(
        select(ReadingSession).where(ReadingSession.article_id == read.id)
    )
    assert other is not None
    other.finished_at = NOW
    await db_session.flush()
    v = await service.view(db_session, plan, rules=RULES, tz=UTC_ZONE, now=NOW)
    assert {p.item.kind: p.complete for p in v.progress} == {
        "practice": False,
        "reading": True,
        "writing": True,
    }


async def test_confirm_decline_undo(db_session: AsyncSession) -> None:
    user_id, tenant_id = await new_user(db_session)
    db_session.add(UserWordBook(user_id=user_id, book_id="cet4", daily_new=4))
    await due_cards(db_session, user_id, 2)
    await words(db_session, 6)
    plan = await today(db_session, user_id, tenant_id)

    # Adjusted within what is open today (Q48c): 2 due, 4 new allowed.
    plan = await service.confirm(
        db_session,
        user_id,
        plan.id,
        choice=PlanChoice(review=50, new_words=1),
        rules=RULES,
        tz=UTC_ZONE,
        now=NOW,
    )
    assert plan.status == "applied" and plan.decided_at == NOW
    assert plan.choice == {
        "review": 2,
        "new_words": 1,
        "practice": False,
        "reading": False,
        "writing": False,
    }
    # Confirming again is a no-op; adjusting a confirmed plan is not allowed.
    assert (
        await service.confirm(db_session, user_id, plan.id, rules=RULES, tz=UTC_ZONE, now=NOW)
    ).status == "applied"
    with pytest.raises(PlanStateError) as err:
        await service.confirm(
            db_session, user_id, plan.id, choice=PlanChoice(), rules=RULES, tz=UTC_ZONE, now=NOW
        )
    assert err.value.code == "plan_not_pending"
    with pytest.raises(PlanStateError):
        await service.decline(db_session, user_id, plan.id, tz=UTC_ZONE, now=NOW)

    # Undo goes back to waiting (Q48f), keeping the adjusted numbers.
    plan = await service.undo(db_session, user_id, plan.id, tz=UTC_ZONE, now=NOW)
    assert plan.status == "proposed" and plan.decided_at is None
    assert plan.choice["new_words"] == 1

    plan = await service.decline(db_session, user_id, plan.id, tz=UTC_ZONE, now=NOW)
    assert plan.status == "declined"
    with pytest.raises(PlanStateError) as err:
        await service.undo(db_session, user_id, plan.id, tz=UTC_ZONE, now=NOW)
    assert err.value.code == "plan_not_applied"


async def test_only_todays_own_plan(db_session: AsyncSession) -> None:
    user_id, tenant_id = await new_user(db_session)
    other_id, _ = await new_user(db_session)
    plan = await today(db_session, user_id, tenant_id)

    with pytest.raises(PlanStateError) as err:
        await service.confirm(db_session, other_id, plan.id, rules=RULES, tz=UTC_ZONE, now=NOW)
    assert err.value.code == "plan_not_found"
    with pytest.raises(PlanStateError) as err:
        await service.confirm(
            db_session, user_id, plan.id, rules=RULES, tz=UTC_ZONE, now=NOW + timedelta(days=1)
        )
    assert err.value.code == "plan_expired"


async def test_new_cards_are_not_reviews(db_session: AsyncSession) -> None:
    """A word started yesterday and reviewed today is a review, not a new word."""
    user_id, tenant_id = await new_user(db_session)
    [word_id] = await words(db_session, 1)
    await review(
        db_session, user_id, word_id=word_id, rating=1, rules=RULES, now=NOW - timedelta(days=1)
    )
    card = await db_session.scalar(select(UserCard).where(UserCard.user_id == user_id))
    assert card is not None
    plan = await today(db_session, user_id, tenant_id)
    await review(db_session, user_id, word_id=word_id, rating=3, rules=RULES, now=NOW)
    v = await service.view(db_session, plan, rules=RULES, tz=UTC_ZONE, now=NOW)
    assert {p.item.kind: p.done for p in v.progress}.get("review") == 1
