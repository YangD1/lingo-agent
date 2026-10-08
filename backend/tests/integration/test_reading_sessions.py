"""Reading an article: the session, quiz answers and reading ability, due words (43.2)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.reading_graph import build_reading_graph
from app.db.models import (
    ArticleVersion,
    ReadingSession,
    SkillEstimate,
    UserCard,
    UserProfile,
    Word,
)
from app.services.reading.worker import ReadingWorker
from tests.integration.test_reading_versions import add_article, builtins, login
from tests.unit.test_reading_graph import FakeModels

__all__ = ["builtins"]  # the autouse fixture: feeds and two words


@pytest.fixture(autouse=True)
def models(app: FastAPI) -> FakeModels:
    fake = FakeModels()
    app.state.reading_worker = ReadingWorker(
        app.state.sessionmaker,
        build_reading_graph(),
        calls=lambda ctx, config: (fake.rewrite, fake.questions, fake.critique),
    )
    return fake


async def open_ready(client: AsyncClient, app: FastAPI, article_id: int) -> dict:
    await client.post(f"/reading/articles/{article_id}/session")
    await app.state.reading_worker.wait_idle()
    response = await client.post(f"/reading/articles/{article_id}/session")
    assert response.status_code == 200
    return response.json()


async def key(db_session: AsyncSession, version_id: str) -> list[int]:
    version = await db_session.get(ArticleVersion, uuid.UUID(version_id), populate_existing=True)
    assert version is not None
    return [q["answer"] for q in version.questions]


async def test_open_starts_the_version_and_picks_up_again(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    await login(client)
    article_id = await add_article(db_session)
    response = await client.post(f"/reading/articles/{article_id}/session")
    assert response.status_code == 200
    body = response.json()
    assert body["version"]["status"] == "generating"
    assert (body["level"], body["original_reason"], body["results"]) == ("A2", None, None)
    assert body["article"]["body"] == "One comet.\n\nTwo comets."

    await app.state.reading_worker.wait_idle()
    again = await client.post(f"/reading/articles/{article_id}/session")
    assert again.json()["id"] == body["id"]
    assert again.json()["version"]["status"] == "ready"
    assert len(list(await db_session.scalars(select(ReadingSession)))) == 1


async def test_first_answers_count_and_move_reading_ability(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    user_id = await login(client)
    article_id = await add_article(db_session)
    body = await open_ready(client, app, article_id)
    answers = await key(db_session, body["version"]["id"])
    url = f"/reading/sessions/{body['id']}/answers"

    bad = await client.post(url, json={"choices": answers[:-1]})
    assert (bad.status_code, bad.json()["detail"]["code"]) == (422, "invalid_answers")

    choices = [answers[0] + 1 if answers[0] == 0 else 0, *answers[1:]]
    response = await client.post(url, json={"choices": choices})
    assert response.status_code == 200
    graded = response.json()
    assert graded["counted"] is True
    assert [r["correct"] for r in graded["results"]] == [False, True, True, True, True]
    assert [r["answer"] for r in graded["results"]] == answers
    assert graded["results"][1]["evidence"].startswith("Fact 2 ")

    ability = await db_session.scalar(
        select(SkillEstimate)
        .where(SkillEstimate.user_id == user_id, SkillEstimate.skill == "reading")
        .execution_options(populate_existing=True)
    )
    assert ability is not None
    assert ability.attempts == 5
    assert ability.rating > -1.5  # started at A2's anchor; four of five right
    rating = ability.rating

    # Later answers get the first results back and count for nothing.
    again = (await client.post(url, json={"choices": answers})).json()
    assert again["counted"] is False
    assert again["results"] == graded["results"]
    await db_session.refresh(ability)
    assert (ability.attempts, ability.rating) == (5, rating)

    reopened = await open_ready(client, app, article_id)
    assert reopened["results"] == graded["results"]
    assert reopened["finished_at"] is not None


async def test_reading_ability_is_on_the_cefr_scale(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    await login(client)
    article_id = await add_article(db_session)
    body = await open_ready(client, app, article_id)
    answers = await key(db_session, body["version"]["id"])
    await client.post(f"/reading/sessions/{body['id']}/answers", json={"choices": answers})

    learner = (await client.get("/learner")).json()
    reading = next(s for s in learner["skills"] if s["skill"] == "reading")
    assert reading["cefr"] in ("A2", "B1")
    dashboard = (await client.get("/dashboard")).json()
    point = next(s for s in dashboard["skills"] if s["skill"] == "reading")
    assert point["position"] is not None


async def test_answered_session_keeps_its_version_after_a_level_change(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    user_id = await login(client)
    article_id = await add_article(db_session)
    body = await open_ready(client, app, article_id)
    answers = await key(db_session, body["version"]["id"])
    await client.post(f"/reading/sessions/{body['id']}/answers", json={"choices": answers})

    reading = await db_session.scalar(
        select(ReadingSession).where(ReadingSession.user_id == user_id)
    )
    assert reading is not None

    profile = await db_session.get(UserProfile, user_id)
    if profile is None:
        db_session.add(UserProfile(user_id=user_id, cefr_level="B2"))
    else:
        profile.cefr_level = "B2"
    await db_session.commit()

    again = (await client.post(f"/reading/articles/{article_id}/session")).json()
    assert again["version"]["id"] == body["version"]["id"]
    assert (again["level"], again["version"]["level"]) == ("A2", "A2")


async def test_summary_only_reads_the_original_without_questions(
    client: AsyncClient, db_session: AsyncSession, models: FakeModels
) -> None:
    await login(client)
    article_id = await add_article(db_session, summary_only=True)
    body = (await client.post(f"/reading/articles/{article_id}/session")).json()
    assert (body["version"], body["original_reason"]) == (None, "summary_only")
    assert models.rewrites == []

    response = await client.post(f"/reading/sessions/{body['id']}/answers", json={"choices": []})
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "no_questions")


async def test_marks_due_words_of_the_text_shown(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    user_id = await login(client)
    article_id = await add_article(db_session)
    words = {w.word: w.id for w in await db_session.scalars(select(Word))}
    now = datetime.now(UTC)
    db_session.add_all(
        [
            UserCard(
                user_id=user_id,
                word_id=words["comet"],
                source="manual",
                status="learning",
                state=2,
                due=now - timedelta(hours=1),
            ),
            # Due tomorrow: not marked.
            UserCard(
                user_id=user_id,
                word_id=words["light"],
                source="manual",
                status="learning",
                state=2,
                due=now + timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()

    body = await open_ready(client, app, article_id)
    marks = await client.get(f"/reading/sessions/{body['id']}/marks")
    assert marks.status_code == 200
    assert marks.json()["due"] == [{"word_id": words["comet"], "form": "comet"}]
    # The original ("One comet. Two comets.") has it too.
    original = (await client.get(f"/reading/sessions/{body['id']}/marks?original=true")).json()
    assert original["due"] == [{"word_id": words["comet"], "form": "comet"}]


async def test_another_learners_session_is_not_found(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    await login(client)
    article_id = await add_article(db_session)
    body = (await client.post(f"/reading/articles/{article_id}/session")).json()
    await app.state.reading_worker.wait_idle()

    await login(client)  # another learner
    for response in (
        await client.get(f"/reading/sessions/{body['id']}/marks"),
        await client.post(f"/reading/sessions/{body['id']}/answers", json={"choices": [0]}),
    ):
        assert (response.status_code, response.json()["detail"]["code"]) == (
            404,
            "session_not_found",
        )
