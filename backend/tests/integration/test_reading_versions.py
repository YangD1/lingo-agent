"""Graded versions of articles: opening one, caching, retries, access (task 42.4)."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.reading_graph import build_reading_graph
from app.db.models import Article, ArticleVersion, Feed, Tenant, UserProfile, Word
from app.services.news.sources import sync_builtin_feeds
from app.services.reading.worker import ReadingWorker
from tests.unit.test_reading_graph import FakeModels


async def login(client: AsyncClient) -> uuid.UUID:
    email = f"{uuid.uuid4()}@example.com"
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


@pytest.fixture(autouse=True)
async def builtins(db_session: AsyncSession) -> None:
    await sync_builtin_feeds(db_session)
    db_session.add_all(
        [
            Word(word="comet", translation="彗星", frq=12000),
            Word(word="light", translation="光", frq=300),
        ]
    )
    await db_session.commit()


@pytest.fixture
def models(app: FastAPI) -> FakeModels:
    fake = FakeModels()
    app.state.reading_worker = ReadingWorker(
        app.state.sessionmaker,
        build_reading_graph(),
        calls=lambda ctx, config: (fake.rewrite, fake.questions, fake.critique),
    )
    return fake


async def add_article(
    session: AsyncSession, *, summary_only: bool = False, license: str | None = None
) -> int:
    feed = await session.scalar(select(Feed).where(Feed.builtin_key == "nasa"))
    assert feed is not None
    article = Article(
        feed_id=feed.id,
        guid=str(uuid.uuid4()),
        url="https://example.com/a",
        title="A comet seen",
        published_at=datetime.now(UTC),
        body="One comet.\n\nTwo comets.",
        summary_only=summary_only,
        license=license or feed.license,
        word_count=600,
        tags=[],
    )
    session.add(article)
    await session.commit()
    return article.id


async def test_open_writes_a_version_once(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    await login(client)
    article_id = await add_article(db_session)
    response = await client.post(f"/reading/articles/{article_id}/version")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["stage"], body["level"]) == ("generating", "rewriting", "A2")
    assert body["article"]["title"] == "A comet seen"

    await app.state.reading_worker.wait_idle()
    response = await client.get(f"/reading/versions/{body['id']}")
    assert response.status_code == 200
    ready = response.json()
    assert (ready["status"], ready["stage"], ready["error_code"]) == ("ready", None, None)
    assert ready["title"] == "Comet news"
    assert len(ready["paragraphs"]) == 6
    assert ready["word_count"] == 300
    # "comet" is past A2's rank cut; "light" is not.
    assert [(w["word"], w["form"]) for w in ready["glossary"]] == [("comet", "comet")]
    assert len(ready["questions"]) == 5
    assert set(ready["questions"][0]) == {"question", "options"}

    stored = await db_session.get(ArticleVersion, uuid.UUID(body["id"]))
    assert stored is not None
    assert (stored.model, stored.critic_model, stored.background) == (
        "fake:writer",
        "fake:critic",
        False,
    )
    assert stored.above_level_share == 0.5

    again = await client.post(f"/reading/articles/{article_id}/version")
    assert again.json()["id"] == body["id"]
    assert again.json()["status"] == "ready"
    assert len(models.rewrites) == 1


async def test_two_learners_opening_at_once_share_one_rewrite(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    await login(client)
    article_id = await add_article(db_session)
    first, second = await asyncio.gather(
        client.post(f"/reading/articles/{article_id}/version"),
        client.post(f"/reading/articles/{article_id}/version"),
    )
    assert first.json()["id"] == second.json()["id"]
    await app.state.reading_worker.wait_idle()
    assert len(models.rewrites) == 1


async def test_failed_version_is_written_again_when_opened(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    await login(client)
    article_id = await add_article(db_session)
    models.rewrite_error = RuntimeError("down")
    version_id = (await client.post(f"/reading/articles/{article_id}/version")).json()["id"]
    await app.state.reading_worker.wait_idle()
    failed = (await client.get(f"/reading/versions/{version_id}")).json()
    assert (failed["status"], failed["error_code"]) == ("failed", "generation_failed")

    models.rewrite_error = None
    retried = (await client.post(f"/reading/articles/{article_id}/version")).json()
    assert (retried["id"], retried["status"]) == (version_id, "generating")
    await app.state.reading_worker.wait_idle()
    ready = (await client.get(f"/reading/versions/{version_id}")).json()
    assert (ready["status"], ready["error_code"]) == ("ready", None)


async def test_without_a_model_the_version_fails(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    await login(client)
    article_id = await add_article(db_session)
    version_id = (await client.post(f"/reading/articles/{article_id}/version")).json()["id"]
    await app.state.reading_worker.wait_idle()
    failed = (await client.get(f"/reading/versions/{version_id}")).json()
    assert failed["status"] == "failed"
    assert failed["error_code"] == "no_llm_configured"


@pytest.mark.parametrize(
    ("summary_only", "license", "level", "code"),
    [
        (True, None, None, "summary_only"),
        (False, "unknown", None, "not_rewritable"),
        (False, None, "C2", "level_above"),
    ],
)
async def test_articles_not_rewritten(
    client: AsyncClient,
    db_session: AsyncSession,
    models: FakeModels,
    summary_only: bool,
    license: str | None,
    level: str | None,
    code: str,
) -> None:
    user_id = await login(client)
    if level is not None:
        db_session.add(UserProfile(user_id=user_id, cefr_level=level))
        await db_session.commit()
    article_id = await add_article(db_session, summary_only=summary_only, license=license)
    response = await client.post(f"/reading/articles/{article_id}/version")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    assert models.rewrites == []


async def test_level_follows_the_learner(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    user_id = await login(client)
    db_session.add(UserProfile(user_id=user_id, cefr_level="B1"))
    await db_session.commit()
    article_id = await add_article(db_session)
    body = (await client.post(f"/reading/articles/{article_id}/version")).json()
    assert body["level"] == "B1"
    await app.state.reading_worker.wait_idle()
    assert "Length of the rewrite: 400 to 600 words" in models.rewrites[0]


async def test_versions_stay_in_their_tenant(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, models: FakeModels
) -> None:
    await login(client)
    article_id = await add_article(db_session)
    version_id = (await client.post(f"/reading/articles/{article_id}/version")).json()["id"]
    await app.state.reading_worker.wait_idle()

    await login(client)  # another learner, in their own tenant
    response = await client.get(f"/reading/versions/{version_id}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "version_not_found"
    missing = await client.post("/reading/articles/999999/version")
    assert missing.json()["detail"]["code"] == "article_not_found"


async def test_recover_fails_versions_cut_off_by_a_restart(
    app: FastAPI, db_session: AsyncSession, client: AsyncClient
) -> None:
    await login(client)
    article_id = await add_article(db_session)
    tenant = await db_session.scalar(select(Tenant).limit(1))
    assert tenant is not None
    db_session.add(
        ArticleVersion(tenant_id=tenant.id, article_id=article_id, level="A2", status="generating")
    )
    await db_session.commit()
    assert await app.state.reading_worker.recover() == 1
    version = await db_session.scalar(select(ArticleVersion))
    assert version is not None
    await db_session.refresh(version)
    assert (version.status, version.error_code) == ("failed", "interrupted")
