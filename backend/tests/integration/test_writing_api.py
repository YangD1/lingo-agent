"""Writing API (task 38.3): submit and poll, history, delete with mastery replayed,
length limits, the fixed tasks, and other learners' submissions."""

from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.runnables import RunnableConfig
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import CEFR_LEVELS
from app.agents.exercise_graph import StructuredCall
from app.db.models import KCEvidence, KCMastery, User, UserProfile, WritingSubmission
from app.providers.config import TenantProviderContext
from app.writing.prompts import get_writing_prompts
from app.writing.worker import WritingWorker
from tests.integration.test_chat_send import login
from tests.integration.test_learner_api import switch_to
from tests.integration.test_writing_service import KC, OTHER_KC, TEXT, FakeReview


def fake_worker(app: FastAPI, fake: FakeReview) -> WritingWorker:
    def calls(ctx: TenantProviderContext, config: RunnableConfig) -> StructuredCall:
        return fake

    worker = WritingWorker(app.state.sessionmaker, calls=calls)
    app.state.writing_worker = worker
    return worker


async def call(client: AsyncClient, method: str, url: str, expect: int, **kw: Any) -> Any:
    response = await client.request(method, url, **kw)
    assert response.status_code == expect, response.text
    return response.json() if response.content else None


async def test_submit_poll_list_and_delete(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    await login(client)
    worker = fake_worker(app, FakeReview())
    assert await call(client, "GET", "/writing", 200) == []

    submitted = await call(
        client, "POST", "/writing", 202, json={"text": TEXT, "prompt": "a2-last-weekend task"}
    )
    assert submitted["status"] == "pending" and submitted["corrections"] is None
    assert submitted["word_count"] == 26 and not submitted["from_conversation"]
    await worker.wait_idle()

    done = await call(client, "GET", f"/writing/{submitted['id']}", 200)
    assert done["status"] == "done" and done["model"] == "conn:fake-model"
    assert done["corrections"][0]["corrected"].startswith("Yesterday I walked")
    assert [k["id"] for k in done["kcs"]] == [KC, OTHER_KC]
    assert done["kcs"][0]["name_zh"]

    [brief] = await call(client, "GET", "/writing", 200)
    assert brief["id"] == submitted["id"] and brief["mistakes"] == 3
    assert brief["excerpt"].startswith("Yesterday I walk to the park with my friend. We walk")

    assert await db_session.scalar(select(func.count()).select_from(KCMastery)) == 2
    await call(client, "DELETE", f"/writing/{submitted['id']}", 204)
    await call(client, "GET", f"/writing/{submitted['id']}", 404)
    # Its evidence went with it, and the KCs it alone gave evidence on lost their rows.
    assert await db_session.scalar(select(func.count()).select_from(KCEvidence)) == 0
    assert await db_session.scalar(select(func.count()).select_from(KCMastery)) == 0
    await call(client, "DELETE", f"/writing/{submitted['id']}", 404)


async def test_length_limits_are_refused_without_a_model_call(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    await login(client)
    fake = FakeReview()
    fake_worker(app, fake)

    short = await call(client, "POST", "/writing", 422, json={"text": "Hello there, my friend."})
    assert short["detail"]["code"] == "writing_too_short"
    long = await call(client, "POST", "/writing", 422, json={"text": "word " * 801})
    assert long["detail"]["code"] == "writing_too_long"
    too_many_chars = await call(client, "POST", "/writing", 422, json={"text": "a" * 20_001})
    assert too_many_chars["detail"]["code"] == "validation_error"

    assert fake.calls == []
    assert await db_session.scalar(select(func.count()).select_from(WritingSubmission)) == 0


async def test_without_a_model_the_review_fails_with_a_code(
    client: AsyncClient, app: FastAPI
) -> None:
    await login(client)  # no connection configured: the real worker finds no model
    worker: WritingWorker = app.state.writing_worker

    submitted = await call(client, "POST", "/writing", 202, json={"text": TEXT})
    await worker.wait_idle()

    failed = await call(client, "GET", f"/writing/{submitted['id']}", 200)
    assert failed["status"] == "failed" and failed["error_code"] == "no_llm_configured"


async def test_prompts_follow_the_learner_level(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    default = await call(client, "GET", "/writing/prompts", 200)
    assert default["level"] == "A2"  # before placement
    assert [p["id"] for p in default["prompts"]] == [
        p.id for p in get_writing_prompts().by_level["A2"]
    ]

    user_id = await db_session.scalar(select(User.id))
    db_session.add(UserProfile(user_id=user_id, cefr_level="B2"))
    await db_session.commit()
    assert (await call(client, "GET", "/writing/prompts", 200))["level"] == "B2"
    asked = await call(client, "GET", "/writing/prompts", 200, params={"level": "C1"})
    assert asked["level"] == "C1" and asked["prompts"][0]["zh"]
    await call(client, "GET", "/writing/prompts", 422, params={"level": "D1"})


def test_every_level_has_prompts() -> None:
    prompts = get_writing_prompts()
    assert all(len(prompts.by_level[level]) >= 3 for level in CEFR_LEVELS)


async def test_other_learners_submissions_are_not_found(client: AsyncClient, app: FastAPI) -> None:
    await login(client, "a@example.com")
    worker = fake_worker(app, FakeReview())
    mine = await call(client, "POST", "/writing", 202, json={"text": TEXT})
    await worker.wait_idle()

    await login(client, "b@example.com")
    assert await call(client, "GET", "/writing", 200) == []
    await call(client, "GET", f"/writing/{mine['id']}", 404)
    await call(client, "DELETE", f"/writing/{mine['id']}", 404)

    await switch_to(client, "a@example.com")
    assert (await call(client, "GET", f"/writing/{mine['id']}", 200))["status"] == "done"
