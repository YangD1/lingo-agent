"""The dashboard's daily conversation (ADR 0016 §1): one a day, started by the learner."""

from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from langchain_core.messages import HumanMessage, ToolMessage
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation
from app.usage.recorder import UsageRecord
from tests.integration.test_chat_send import connect, login, send
from tests.integration.test_chat_tools import (  # noqa: F401 (fixtures)
    Script,
    _clear_caches,
    activity,
    cards,
    kinds,
    script,
    system_text,
    tool_call,
    usage_records,
)
from tests.integration.test_learner_api import switch_to


async def daily(client: AsyncClient, expect: int = 201, tz: str = "UTC") -> dict[str, Any]:
    response = await client.post(
        "/conversations", json={"purpose": "daily", "locale": "zh-CN", "tz": tz}
    )
    assert response.status_code == expect, response.text
    body: dict[str, Any] = response.json()
    return body


async def today(client: AsyncClient, tz: str = "UTC") -> dict[str, Any] | None:
    response = await client.get("/conversations/today", params={"tz": tz})
    assert response.status_code == 200, response.text
    body: dict[str, Any] | None = response.json()
    return body


async def test_one_conversation_a_day(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    assert await today(client) is None  # nothing is created by just looking

    created = await daily(client)
    assert created["purpose"] == "daily" and created["focus_kc"] is None
    assert created["title"].startswith("今天的学习 · ")
    # A second first message (another tab) shares it.
    assert (await daily(client, expect=200))["id"] == created["id"]
    assert (await today(client))["id"] == created["id"]  # type: ignore[index]
    listed = (await client.get("/conversations")).json()
    assert [(c["id"], c["purpose"]) for c in listed] == [(created["id"], "daily")]

    # Yesterday's is not today's: the next day starts a new one.
    await db_session.execute(
        update(Conversation).values(created_at=Conversation.created_at - timedelta(days=1))
    )
    await db_session.commit()
    assert await today(client) is None
    assert (await daily(client))["id"] != created["id"]


async def test_today_is_the_learners_own(client: AsyncClient) -> None:
    await login(client, "first@example.com")
    mine = await daily(client)
    await login(client, "second@example.com")

    assert await today(client) is None
    assert (await daily(client))["id"] != mine["id"]

    await switch_to(client, "first@example.com")
    assert (await today(client))["id"] == mine["id"]  # type: ignore[index]


async def test_the_tutor_answers_with_todays_brief_and_cards_within_it(
    client: AsyncClient,
    script: Script,  # noqa: F811
    usage_records: list[UsageRecord],  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "openai")
    conversation = (await daily(client))["id"]
    # No test yet and no word book: those are what the engine suggests.
    script.replies = [
        [
            tool_call("suggest_link", kind="placement"),
            tool_call("suggest_link", kind="vocab_review"),  # not among the suggestions
        ],
        "Start with the placement test.",
    ]

    status, events, _ = await send(client, conversation, "What should I study today?")

    assert status == 200 and kinds(events, "done")
    offered, messages = script.calls[0]
    assert offered is not None
    prompt = system_text(messages)
    assert "today's study, from the dashboard" in prompt
    assert "What the learning engine suggests now" in prompt
    assert "Take the placement test: never taken" in prompt
    # No opening cue: the learner's own message is the last one.
    assert isinstance(messages[-1], HumanMessage)
    assert messages[-1].text == "What should I study today?"
    results = [m for m in script.calls[1][1] if isinstance(m, ToolMessage)]
    assert [r.status for r in results] == ["success", "error"]
    shown = [(c["kind"], c["params"]) for c in await cards(client, conversation)]
    assert shown == [("link", {"kind": "placement"})]
    assert [r.task for r in usage_records] == ["chat", "chat_tools"]
    (load,) = [
        a
        for a in await activity(client, conversation)
        if a["kind"] == "step" and a["name"] == "load_context"
    ]
    assert load["summary"]["planning"] is True


async def test_a_daily_conversation_has_no_opening(client: AsyncClient) -> None:
    await login(client)
    await connect(client, "openai")
    conversation = (await daily(client))["id"]

    response = await client.post(f"/conversations/{conversation}/opening")

    assert (response.status_code, response.json()["detail"]["code"]) == (409, "not_practice")


async def test_daily_is_not_practice(client: AsyncClient) -> None:
    await login(client)
    response = await client.post(
        "/conversations", json={"purpose": "daily", "focus_kc_id": "g.word_order_svo"}
    )
    assert (response.status_code, response.json()["detail"]["code"]) == (
        422,
        "conflicting_purpose",
    )
