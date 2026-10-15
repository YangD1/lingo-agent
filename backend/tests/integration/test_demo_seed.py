"""The demo seed (task 72.3): engine-made history, repeatable, and no other account."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.learner import mastery_state
from app.adaptive.rules import get_rules
from app.dashboard.service import dashboard
from app.db.models import (
    Diagnosis,
    KCMastery,
    Memory,
    PlacementSession,
    ReadingSession,
    ReviewLog,
    SkillEstimate,
    SpeakingSession,
    User,
    UserCard,
    WritingSubmission,
)
from app.db.session import create_sessionmaker
from app.demo import content
from app.demo.seed import DEFAULT_EMAIL, REVIEW_DAYS, NotDemoEmailError, seed
from app.services.vocab.import_ecdict import import_csv
from tests.conftest import TEST_DATABASE_URL

SAMPLE = Path(__file__).parents[1] / "fixtures" / "ecdict_sample.csv"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


async def _snapshot(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Every engine-made number of the account, without row ids."""
    mastery = await session.scalars(
        select(KCMastery).where(KCMastery.user_id == user_id).order_by(KCMastery.kc_id)
    )
    skills = await session.scalars(
        select(SkillEstimate).where(SkillEstimate.user_id == user_id).order_by(SkillEstimate.skill)
    )
    cards = await session.scalars(
        select(UserCard).where(UserCard.user_id == user_id).order_by(UserCard.word_id)
    )
    placement = await session.scalar(
        select(PlacementSession).where(PlacementSession.user_id == user_id)
    )
    diagnosis = await session.scalar(select(Diagnosis).where(Diagnosis.user_id == user_id))
    assert placement is not None and diagnosis is not None
    return {
        "mastery": [
            (m.kc_id, round(m.p_mastery, 6), m.mastered_at, m.gate_ready_at, m.due) for m in mastery
        ],
        "skills": [(s.skill, round(s.rating, 6), s.attempts) for s in skills],
        "cards": [(c.word_id, c.status, c.state, c.due, c.stability) for c in cards],
        "placement": placement.result,
        "diagnosis": [
            (c["kc_ids"], len(c["evidence_ids"]), c["hypothesis"]) for c in diagnosis.root_causes
        ],
        "reviews": await session.scalar(
            select(func.count()).select_from(ReviewLog).where(ReviewLog.user_id == user_id)
        ),
        "memories": await session.scalar(
            select(func.count()).select_from(Memory).where(Memory.user_id == user_id)
        ),
    }


@pytest.fixture
async def words() -> None:
    await import_csv(TEST_DATABASE_URL, SAMPLE)


async def test_seed_twice_gives_the_same_history_and_leaves_others_alone(
    db_engine: AsyncEngine, db_session: AsyncSession, client: AsyncClient, words: None
) -> None:
    response = await client.post(
        "/auth/register", json={"email": "someone@example.com", "password": "password123"}
    )
    assert response.status_code == 201
    other = uuid.UUID(response.json()["id"])
    maker = create_sessionmaker(db_engine)

    first = await seed(maker, InMemorySaver(), password="demo-pass-1", now=NOW)
    async with maker() as session:
        before = await _snapshot(session, first.user_id)
    second = await seed(maker, InMemorySaver(), password="demo-pass-2", now=NOW)
    async with maker() as session:
        after = await _snapshot(session, second.user_id)
        users = set(await session.scalars(select(User.id)))

    assert second.user_id != first.user_id  # recreated, not patched
    assert after == before
    assert users == {other, second.user_id}
    assert before["reviews"] > 0 and before["memories"] == len(content.MEMORIES) + 1
    async with maker() as session:
        demo = await session.get(User, second.user_id)
        assert demo is not None and demo.setup_completed_at == NOW  # no setup guide


async def test_the_demo_has_a_weak_point_a_consolidating_one_and_a_streak(
    db_engine: AsyncEngine, db_session: AsyncSession, client: AsyncClient, words: None
) -> None:
    maker = create_sessionmaker(db_engine)
    # The real clock: the dashboard counts the streak back from today.
    seeded = await seed(maker, InMemorySaver(), password="demo-pass")
    rules = get_rules()
    async with maker() as session:
        rows = {
            m.kc_id: m
            for m in await session.scalars(
                select(KCMastery).where(KCMastery.user_id == seeded.user_id)
            )
        }
        diagnosis = await session.scalar(
            select(Diagnosis).where(Diagnosis.user_id == seeded.user_id)
        )
        done = {
            "writing": await session.scalar(
                select(WritingSubmission.status).where(WritingSubmission.user_id == seeded.user_id)
            ),
            "reading": await session.scalar(
                select(ReadingSession.finished_at).where(ReadingSession.user_id == seeded.user_id)
            ),
            "speaking": await session.scalar(
                select(SpeakingSession.counted).where(SpeakingSession.user_id == seeded.user_id)
            ),
        }

    assert mastery_state(rows[content.WEAK].p_mastery, rules) == "weak"
    learned = rows[content.LEARNED]
    assert learned.mastered_at is not None and learned.due is not None
    consolidating = rows[content.CONSOLIDATING]
    assert consolidating.mastered_at is None and consolidating.gate_ready_at is not None
    assert diagnosis is not None and diagnosis.root_causes[0]["kc_ids"] == [content.WEAK]
    assert done == {"writing": "done", "reading": done["reading"], "speaking": True}
    assert done["reading"] is not None

    response = await client.post(
        "/auth/login", json={"email": DEFAULT_EMAIL, "password": "demo-pass"}
    )
    assert response.status_code == 200
    response = await client.get("/dashboard", params={"tz": "UTC"})
    assert response.status_code == 200
    board = response.json()
    assert board["summary"]["streak_days"] == REVIEW_DAYS


async def test_only_demo_addresses_are_seeded(db_engine: AsyncEngine) -> None:
    with pytest.raises(NotDemoEmailError):
        await seed(create_sessionmaker(db_engine), InMemorySaver(), email="me@example.com")


async def test_the_streak_holds_when_seeded_just_after_midnight(
    db_engine: AsyncEngine, db_session: AsyncSession, words: None
) -> None:
    # Seeded at 00:13 (the screenshots run once was), "yesterday" must still be yesterday.
    early = datetime(2026, 10, 14, 0, 13, tzinfo=UTC)
    maker = create_sessionmaker(db_engine)
    seeded = await seed(maker, InMemorySaver(), password="demo-pass", now=early)
    async with maker() as session:
        board = await dashboard(
            session,
            seeded.user_id,
            rules=get_rules(),
            catalog=get_grammar_catalog(),
            tz=ZoneInfo("UTC"),
            now=early,
        )

    assert board.summary.streak_days == REVIEW_DAYS
