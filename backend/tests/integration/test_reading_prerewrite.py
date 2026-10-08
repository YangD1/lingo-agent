"""Rewriting new articles ahead of time: the `article_prerewrite` job (task 42.5)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.reading_graph import build_reading_graph
from app.db.models import Article, ArticleVersion, Feed, Tenant, TenantMember, UserProfile
from app.scheduler import jobs, prefs
from app.scheduler.jobs import JobContext
from app.services.news.sources import sync_builtin_feeds
from app.services.reading.worker import ReadingWorker
from tests.unit.test_reading_graph import FakeModels

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def builtins(db_session: AsyncSession) -> None:
    await sync_builtin_feeds(db_session)
    await db_session.commit()


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch) -> FakeModels:
    fake = FakeModels()

    def make(sessionmaker: async_sessionmaker[AsyncSession]) -> ReadingWorker:
        return ReadingWorker(
            sessionmaker,
            build_reading_graph(),
            calls=lambda ctx, config: (fake.rewrite, fake.questions, fake.critique),
            clock=lambda: NOW,
        )

    monkeypatch.setattr(jobs, "make_reading_worker", make)
    return fake


async def learner(client: AsyncClient, session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    email = f"{uuid.uuid4()}@example.com"
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    user_id = uuid.UUID(response.json()["id"])
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user_id)
    )
    assert tenant_id is not None
    return user_id, tenant_id


async def add(
    session: AsyncSession, title: str, age: timedelta, *, summary_only: bool = False
) -> int:
    feed = await session.scalar(select(Feed).where(Feed.builtin_key == "nasa"))
    assert feed is not None
    article = Article(
        feed_id=feed.id,
        guid=title,
        url=f"https://example.com/{title}",
        title=title,
        published_at=NOW - age,
        body="One comet.\n\nTwo comets.",
        summary_only=summary_only,
        license=feed.license,
        word_count=600,
        tags=[],
    )
    session.add(article)
    await session.commit()
    return article.id


async def run(app: FastAPI) -> str | None:
    ctx = JobContext(app.state.sessionmaker, NOW, uuid.uuid4(), None)
    return await jobs.article_prerewrite(ctx)


async def versions(session: AsyncSession) -> list[ArticleVersion]:
    session.expire_all()
    return list(await session.scalars(select(ArticleVersion).order_by(ArticleVersion.article_id)))


async def test_rewrites_the_newest_articles_once(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    user_id, tenant_id = await learner(client, db_session)
    db_session.add(UserProfile(user_id=user_id, cefr_level="B1"))
    await db_session.commit()
    newest = await add(db_session, "newest", timedelta(hours=1))
    second = await add(db_session, "second", timedelta(days=1))
    await add(db_session, "third", timedelta(days=2))
    await add(db_session, "teaser", timedelta(minutes=5), summary_only=True)
    await add(db_session, "old", timedelta(days=5))

    assert await run(app) is None
    written = await versions(db_session)
    assert [v.article_id for v in written] == sorted([newest, second])
    assert {(v.tenant_id, v.level, v.status, v.background) for v in written} == {
        (tenant_id, "B1", "ready", True)
    }
    assert "Length of the rewrite: 400 to 600 words" in models.rewrites[0]

    assert await run(app) is None
    assert len(await versions(db_session)) == 2
    assert len(models.rewrites) == 2


async def test_skips_learners_who_switched_it_off(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    user_id, _ = await learner(client, db_session)
    await prefs.set_enabled(db_session, user_id, prefs.ARTICLE_PREREWRITE, False)
    await db_session.commit()
    await add(db_session, "newest", timedelta(hours=1))
    assert await run(app) is None
    assert await versions(db_session) == []


async def test_skips_learners_who_read_originals(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    user_id, _ = await learner(client, db_session)
    db_session.add(UserProfile(user_id=user_id, cefr_level="C2"))
    await db_session.commit()
    await add(db_session, "newest", timedelta(hours=1))
    assert await run(app) is None
    assert await versions(db_session) == []


async def test_stops_at_the_budget(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    _, tenant_id = await learner(client, db_session)
    await db_session.execute(
        update(Tenant).where(Tenant.id == tenant_id).values(background_daily_tokens=0)
    )
    await db_session.commit()
    await add(db_session, "newest", timedelta(hours=1))
    assert await run(app) == "budget_exhausted"
    assert await versions(db_session) == []
    assert models.rewrites == []


async def test_leaves_versions_learners_opened_alone(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    _, tenant_id = await learner(client, db_session)
    article_id = await add(db_session, "newest", timedelta(hours=1))
    db_session.add(
        ArticleVersion(
            tenant_id=tenant_id,
            article_id=article_id,
            level="A2",
            status="failed",
            error_code="generation_failed",
        )
    )
    await db_session.commit()
    assert await run(app) is None
    [version] = await versions(db_session)
    assert version.status == "failed"
    assert models.rewrites == []
