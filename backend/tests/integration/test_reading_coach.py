"""reading_coach (task 43.3): "ask the tutor" on the reading page opens a conversation
about the article; each turn the coach gets the article, without tools."""

from typing import Any

import pytest
from httpx import AsyncClient
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import chat_graph
from app.agents.routing import Route
from app.db.models import Article, ArticleVersion, Tenant
from app.providers.config import TenantProviderContext
from app.usage.recorder import UsageRecord
from tests.integration.test_chat_send import send
from tests.integration.test_chat_tools import (
    Script,
    _clear_caches,  # noqa: F401
    activity,
    kinds,
    script,  # noqa: F401
    system_text,
    usage_records,  # noqa: F401
)
from tests.integration.test_chat_tools import ready as free_chat
from tests.integration.test_reading_versions import add_article, builtins

__all__ = ["builtins"]  # the autouse fixture: feeds and two words

LONG = " ".join(["word"] * 80)


@pytest.fixture(autouse=True)
def classified(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records whatever the free-chat classifier is asked; it never should be here."""
    asked: list[str] = []

    async def classify(
        ctx: TenantProviderContext, text: str, previous: str, config: RunnableConfig
    ) -> Route:
        asked.append(text)
        return Route.TUTOR

    monkeypatch.setattr(chat_graph, "classify", classify)
    return asked


async def reading_conversation(client: AsyncClient, article_id: int) -> dict[str, Any]:
    response = await client.post("/conversations", json={"article_id": article_id})
    assert response.status_code == 201
    return dict(response.json())


async def test_asking_about_an_article_opens_one_conversation_for_it(
    client: AsyncClient,
    db_session: AsyncSession,
    script: Script,  # noqa: F811
) -> None:
    await free_chat(client)
    article_id = await add_article(db_session)
    body = await reading_conversation(client, article_id)
    assert (body["article_id"], body["purpose"], body["title"]) == (
        article_id,
        None,
        "Reading: A comet seen",
    )
    # Asking again before saying anything returns the same one.
    again = await client.post("/conversations", json={"article_id": article_id})
    assert (again.status_code, again.json()["id"]) == (200, body["id"])
    # It never speaks first (Q43h).
    opening = await client.post(f"/conversations/{body['id']}/opening")
    assert (opening.status_code, opening.json()["detail"]["code"]) == (409, "not_practice")

    for payload, status, code in (
        ({"article_id": 999999}, 404, "article_not_found"),
        ({"article_id": article_id, "purpose": "planning"}, 422, "conflicting_purpose"),
    ):
        response = await client.post("/conversations", json=payload)
        assert (response.status_code, response.json()["detail"]["code"]) == (status, code)


async def test_the_coach_reads_the_original_without_tools(
    client: AsyncClient,
    db_session: AsyncSession,
    script: Script,  # noqa: F811
    usage_records: list[UsageRecord],  # noqa: F811
    classified: list[str],
) -> None:
    await free_chat(client)
    article_id = await add_article(db_session)
    conversation = (await reading_conversation(client, article_id))["id"]
    script.replies = ["A comet is an icy body."]

    status, events, _ = await send(client, conversation, f"What is a comet? {LONG}")

    assert status == 200
    assert "".join(e["text"] for e in kinds(events, "token")) == "A comet is an icy body."
    offered, messages = script.calls[-1]
    assert offered is None
    prompt = system_text(messages)
    assert '<article title="A comet seen">\nOne comet.\n\nTwo comets.\n</article>' in prompt
    assert "(the original text)" in prompt
    assert "not instructions" in prompt
    # Not classified, however long: the route is fixed by the conversation.
    assert classified == []

    (step,) = [r for r in await activity(client, conversation) if r["name"] == "reading_context"]
    assert step["status"] == "ok"
    assert step["summary"] == {"article_id": article_id, "level": None, "words": 4}
    assert "reading_coach" in {r.task for r in usage_records}
    assert "chat" not in {r.task for r in usage_records}


async def test_the_coach_reads_the_version_at_my_level(
    client: AsyncClient,
    db_session: AsyncSession,
    script: Script,  # noqa: F811
) -> None:
    await free_chat(client)
    article_id = await add_article(db_session)
    tenant_id = await db_session.scalar(select(Tenant.id))
    assert tenant_id is not None
    db_session.add(
        ArticleVersion(
            tenant_id=tenant_id,
            article_id=article_id,
            level="A2",
            status="ready",
            title="Comet news",
            paragraphs=["A comet is in the sky.", "You can see it at night."],
            word_count=12,
        )
    )
    await db_session.commit()
    conversation = (await reading_conversation(client, article_id))["id"]
    script.replies = ["Look at the first sentence."]

    await send(client, conversation, "Where is the comet?")

    prompt = system_text(script.calls[-1][1])
    assert "rewritten for their level (A2)" in prompt
    assert "A comet is in the sky.\n\nYou can see it at night." in prompt
    assert "Two comets." not in prompt
    (step,) = [r for r in await activity(client, conversation) if r["name"] == "reading_context"]
    assert step["summary"] == {"article_id": article_id, "level": "A2", "words": 12}


async def test_once_the_article_is_gone_the_tutor_answers(
    client: AsyncClient,
    db_session: AsyncSession,
    script: Script,  # noqa: F811
) -> None:
    await free_chat(client)
    article_id = await add_article(db_session)
    conversation = (await reading_conversation(client, article_id))["id"]
    article = await db_session.get(Article, article_id)
    await db_session.delete(article)
    await db_session.commit()
    script.replies = ["Sure, let's talk."]

    status, _, _ = await send(client, conversation, "Can we talk?")

    assert status == 200
    prompt = system_text(script.calls[-1][1])
    assert "<article" not in prompt
    listed = (await client.get("/conversations")).json()
    assert any(c["id"] == conversation and c["article_id"] is None for c in listed)
