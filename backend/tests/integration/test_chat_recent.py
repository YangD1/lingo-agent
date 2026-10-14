"""The last days of study in today's brief (ADR 0041 §3): counted by code."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.chat.recent import RecentStudy, load_recent, render_recent
from app.db.models import Diagnosis, KCEvidence, LLMUsage, Tenant, User

CATALOG = get_grammar_catalog()
KC = "g.word_order_svo"
UTC_ZONE = ZoneInfo("UTC")
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


async def _learner(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = Tenant(name="t", kind="personal")
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add_all([tenant, user])
    await session.flush()
    return user.id, tenant.id


def _turn(user_id: uuid.UUID, tenant_id: uuid.UUID, days_ago: int, task: str = "chat") -> LLMUsage:
    return LLMUsage(
        tenant_id=tenant_id,
        user_id=user_id,
        task=task,
        connection_name="c",
        model="m",
        latency_ms=1,
        status="ok",
        created_at=NOW - timedelta(days=days_ago),
    )


def _mistake(user_id: uuid.UUID, days_ago: int, source: str = "chat") -> KCEvidence:
    return KCEvidence(
        user_id=user_id,
        kc_id=KC,
        correct=False,
        evidence="production",
        source=source,
        error_type="wrong_form",
        severity="medium",
        created_at=NOW - timedelta(days=days_ago),
    )


async def test_counts_the_last_seven_days(db_session: AsyncSession) -> None:
    me, tenant = await _learner(db_session)
    db_session.add_all(
        [
            _turn(me, tenant, 1),
            _turn(me, tenant, 1),
            _turn(me, tenant, 3),
            _turn(me, tenant, 9),  # before the window: not counted, but a studied day
            _turn(me, tenant, 2, task="daily_opening"),  # the tutor's own: not a turn
            _mistake(me, 1),
            _mistake(me, 2),
            _mistake(me, 2, source="placement"),  # a test item, not a mistake in use
            _mistake(me, 8),
            Diagnosis(
                user_id=me,
                trigger="weekly",
                target_kc_ids=[KC],
                root_causes=[{"hypothesis": "Puts the verb last, as in Japanese."}],
                language="en",
                rules_version=get_rules().version,
                created_at=NOW - timedelta(days=2),
            ),
        ]
    )
    await db_session.flush()

    recent = await load_recent(db_session, me, tz=UTC_ZONE, catalog=CATALOG, now=NOW)

    assert (recent.studied_days, recent.chat_turns) == (2, 3)
    assert recent.last_before_today == date(2026, 10, 14)
    assert [(m.kc.id, m.mistakes) for m in recent.mistakes] == [(KC, 2)]
    assert recent.diagnosis == "Puts the verb last, as in Japanese."
    text = "\n".join(render_recent(recent))
    assert "Days studied: 2 of 7; last before today: 1 day ago (2026-10-14)" in text
    assert f"`{KC}`" in text and "(data)" in text


async def test_nothing_studied(db_session: AsyncSession) -> None:
    me, _ = await _learner(db_session)

    recent = await load_recent(db_session, me, tz=UTC_ZONE, catalog=CATALOG, now=NOW)

    assert recent.nothing and recent.last_before_today is None and recent.diagnosis is None
    text = "\n".join(render_recent(recent))
    assert "last before today: never before today" in text
    assert "Nothing studied in these days." in text


def test_practice_share_is_shown_only_with_practice() -> None:
    today = date(2026, 10, 15)
    with_practice = "\n".join(
        render_recent(RecentStudy(today=today, practice=8, practice_correct=6))
    )
    without = "\n".join(render_recent(RecentStudy(today=today, reviews=3)))

    assert "Grammar practice items: 8, 6 right (75%)" in with_practice
    assert "Grammar practice" not in without
