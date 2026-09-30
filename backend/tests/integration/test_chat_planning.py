"""The study-planning conversation (ADR 0015 §6): opened from the placement result."""

from typing import Any

from httpx import AsyncClient
from langchain_core.messages import HumanMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.placement.writeback import save_result
from app.db.models import PlacementSession, User
from app.usage.recorder import UsageRecord
from tests.integration.test_chat_send import connect, login, parse_sse, send
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
from tests.integration.test_placement_writeback import BANK, CATALOG, RULES, finished_result


async def placed(db: AsyncSession) -> None:
    """The logged-in learner finishes a placement test (a third of grammar wrong)."""
    user = await db.scalar(select(User).where(User.email == "learner@example.com"))
    assert user is not None
    test = PlacementSession(
        user_id=user.id, status="in_progress", stage="vocab", seed=1, rules_version=RULES.version
    )
    db.add(test)
    await db.commit()
    saved = await save_result(
        db,
        user_id=user.id,
        session_id=test.id,
        result=finished_result(7),
        rules=RULES,
        catalog=CATALOG,
        bank=BANK,
    )
    assert saved


async def plan(client: AsyncClient, expect: int = 201) -> dict[str, Any]:
    response = await client.post("/conversations", json={"purpose": "planning", "locale": "zh-CN"})
    assert response.status_code == expect, response.text
    body: dict[str, Any] = response.json()
    return body


async def open_plan(client: AsyncClient, conversation_id: str) -> list[tuple[str, Any]]:
    response = await client.post(f"/conversations/{conversation_id}/opening")
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


async def test_the_tutor_opens_with_the_result_and_the_engines_suggestions(
    client: AsyncClient,
    db_session: AsyncSession,
    script: Script,  # noqa: F811
    usage_records: list[UsageRecord],  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "openai")
    await placed(db_session)
    created = await plan(client)
    assert (created["purpose"], created["title"], created["focus_kc"]) == (
        "planning",
        "学习规划",
        None,
    )
    # Pressed twice before anything is said: the same conversation.
    assert (await plan(client, expect=200))["id"] == created["id"]
    script.replies = ["Hi! You're at B1 overall. What are you studying for?"]

    events = await open_plan(client, created["id"])

    assert kinds(events, "done")
    ((offered, messages),) = script.calls
    assert offered is not None  # tools are bound, the scope limits them
    prompt = system_text(messages)
    assert "planning the learner's study" in prompt
    assert "Overall level (CEFR)" in prompt
    assert "What the learning engine suggests now" in prompt
    assert "Grammar points missed in that test" in prompt
    assert isinstance(messages[-1], HumanMessage) and "planning conversation" in messages[-1].text
    assert [r.task for r in usage_records] == ["plan_opening"]
    (load,) = [a for a in await activity(client, created["id"]) if a["kind"] == "step"]
    assert load["summary"]["planning"] is True
    # Once the tutor has spoken, the button starts a fresh conversation.
    assert (await plan(client))["id"] != created["id"]


async def test_cards_stay_within_the_brief(
    client: AsyncClient,
    db_session: AsyncSession,
    script: Script,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "openai")
    await placed(db_session)
    conversation = (await plan(client))["id"]
    await open_plan(client, conversation)
    brief = system_text(script.calls[0][1])
    missed = brief.split("Grammar points missed in that test")[1].split("`")[1]
    script.replies = [
        [
            tool_call("suggest_practice", kc_id=missed),
            tool_call("suggest_link", kind="learner"),
            # Just taken: a retest is not among the suggestions.
            tool_call("suggest_link", kind="placement"),
        ],
        "Here is a start.",
    ]

    await send(client, conversation, "Where do I start?")

    results = [m for m in script.calls[2][1] if isinstance(m, ToolMessage)]
    assert [r.status for r in results] == ["success", "success", "error"]
    assert "not among the suggestions" in results[2].text
    shown = [(c["kind"], c["params"]) for c in await cards(client, conversation)]
    assert shown == [("practice", {"kc_id": missed}), ("link", {"kind": "learner"})]


async def test_planning_needs_no_placement_and_is_not_practice(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "openai")
    conflicting = await client.post(
        "/conversations", json={"purpose": "planning", "focus_kc_id": "g.word_order_svo"}
    )
    assert (conflicting.status_code, conflicting.json()["detail"]["code"]) == (
        422,
        "conflicting_purpose",
    )
    conversation = (await plan(client))["id"]

    await open_plan(client, conversation)

    prompt = system_text(script.calls[0][1])
    assert "None finished yet." in prompt
    listed = (await client.get("/conversations")).json()
    assert [c["purpose"] for c in listed] == ["planning"]
