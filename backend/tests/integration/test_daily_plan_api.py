"""Today's plan over the API, and the tutor's daily plan cards (ADR 0027, task 48.3)."""

import uuid
from typing import Any

from httpx import AsyncClient
from langchain_core.messages import ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Word
from tests.integration.test_chat_daily import daily
from tests.integration.test_chat_send import connect, login, new_conversation, send
from tests.integration.test_chat_tools import (  # noqa: F401 (fixtures)
    Script,
    _clear_caches,
    cards,
    kinds,
    script,
    system_text,
    tool_call,
)

NO_PLAN = {
    "review": 0,
    "new_words": 0,
    "practice": False,
    "reading": False,
    "writing": False,
    "speaking": False,
}


async def plan(client: AsyncClient) -> dict[str, Any]:
    response = await client.get("/plan/today", params={"tz": "UTC"})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/plan/today")).status_code == 401


async def test_drafted_on_first_read_then_confirmed_declined_undone(client: AsyncClient) -> None:
    await login(client)
    first = await plan(client)
    # A new learner: no due words, no word book, no feeds; grammar to practise.
    assert first["status"] == "proposed" and first["card_id"] is None
    assert first["choice"] == {**NO_PLAN, "practice": True}
    (item,) = first["items"]
    assert item["kind"] == "practice" and item["kc"]["name_zh"]
    assert (item["done"], item["target"], item["complete"]) == (0, 1, False)
    assert (first["budget"], first["budget_set"], first["minutes"]) == (20, False, 8)
    assert first["limits"] == {
        "reviews_due": 0,
        "new_left": 0,
        "practice": True,
        "reading": False,
        "max_count": 500,
        "speaking_minutes": 5,
    }
    assert first["estimates"]["review"] == 0.25
    assert first["estimates"]["speaking"] == 10
    assert (await plan(client))["id"] == first["id"]

    url = f"/plan/{first['id']}"
    # Adjusted within today's limits: nothing to review or read, so those stay off.
    asked = {"review": 30, "new_words": 0, "practice": True, "reading": True, "writing": True}
    confirmed = await client.post(f"{url}/confirm", json={"choice": asked, "tz": "UTC"})
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "applied"
    assert body["choice"] == {**NO_PLAN, "practice": True, "writing": True}
    assert [i["kind"] for i in body["items"]] == ["practice", "writing"]
    assert body["minutes"] == 8 + 15

    again = await client.post(f"{url}/confirm", json={"choice": asked})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "plan_not_pending"
    undone = await client.post(f"{url}/undo", json={})
    assert undone.status_code == 200 and undone.json()["status"] == "proposed"
    declined = await client.post(f"{url}/decline", json={})
    assert declined.status_code == 200 and declined.json()["status"] == "declined"
    assert (await plan(client))["status"] == "declined"

    # Someone else's plan is not found.
    await client.post("/auth/logout")
    await login(client, "other@example.com")
    stranger = await client.post(f"{url}/confirm", json={})
    assert stranger.status_code == 404 and stranger.json()["detail"]["code"] == "plan_not_found"


async def test_the_tutor_proposes_a_plan_in_todays_conversation(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "openai")
    drafted = await plan(client)
    conversation = (await daily(client))["id"]
    script.replies = [
        [
            tool_call(
                "propose_daily_plan",
                review=40,
                new_words=10,
                practice=False,
                reading=True,
                writing=True,
            )
        ],
        "Here is a lighter plan.",
    ]

    status, events, _ = await send(client, conversation, "I only have 15 minutes today.")

    assert status == 200
    offered, messages = script.calls[0]
    assert offered is not None and "propose_daily_plan" in offered
    prompt = system_text(messages)
    assert "### Today's plan (drafted, waiting for the learner to confirm it" in prompt
    assert "- One grammar practice set, about 8 min: 0/1 done" in prompt
    assert "Today in all (done and still open): 0 reviews, 0 new words" in prompt
    (card,) = kinds(events, "card")
    assert card["kind"] == "daily_plan" and card["status"] == "proposed"
    params = card["params"]
    assert params["plan_id"] == drafted["id"]
    # Lowered to what is open today; the essay stays.
    assert params["choice"] == {**NO_PLAN, "writing": True}
    assert params["minutes"] == 15
    (result,) = [m for m in script.calls[1][1] if isinstance(m, ToolMessage)]
    assert "today's plan: write one short text (about 15 min)" in str(result.content)

    # The learner adds the practice set back on the card, then confirms.
    choice = {**NO_PLAN, "practice": True, "writing": True}
    applied = await client.post(f"/cards/{card['id']}/apply", json={"choice": choice, "tz": "UTC"})
    assert applied.status_code == 200, applied.text
    assert applied.json()["params"]["minutes"] == 23
    now = await plan(client)
    assert (now["status"], now["card_id"], now["choice"]) == ("applied", card["id"], choice)

    # A plan from a card is undone on the card, which puts back the drafted one.
    refused = await client.post(f"/plan/{now['id']}/undo", json={})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "plan_from_card"
    assert (await client.post(f"/cards/{card['id']}/undo")).json()["status"] == "undone"
    back = await plan(client)
    assert (back["status"], back["card_id"], back["choice"]) == (
        "proposed",
        None,
        drafted["choice"],
    )

    # Only a daily plan card takes a choice.
    shown = await cards(client, conversation)
    assert [c["kind"] for c in shown] == ["daily_plan"]


async def test_only_in_todays_conversation(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "openai")
    conversation = await new_conversation(client)
    args = {"review": 1, "new_words": 1, "practice": True, "reading": False, "writing": False}
    script.replies = [[tool_call("propose_daily_plan", **args)], "Sorry."]

    status, events, _ = await send(client, conversation, "Plan my day.")

    assert status == 200 and not kinds(events, "card")
    (result,) = [m for m in script.calls[1][1] if isinstance(m, ToolMessage)]
    assert result.status == "error"
    assert "only be proposed in today's conversation" in str(result.content)


async def test_other_cards_take_no_choice(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "openai")
    conversation = await new_conversation(client)
    script.replies = [[tool_call("propose_word_book", book_id="cet4")], "Suggested."]
    _, events, _ = await send(client, conversation, "Switch my book to CET-4.")
    (card,) = kinds(events, "card")

    response = await client.post(f"/cards/{card['id']}/apply", json={"choice": NO_PLAN})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "card_not_adjustable"


async def test_a_proposal_reads_what_is_open_now(
    client: AsyncClient,
    script: Script,  # noqa: F811
    db_session: AsyncSession,
) -> None:
    """The plan was drafted before the learner chose a word book: the tutor's plan may
    still include new words, and confirming it carries the new limits (ADR 0027 §1)."""
    await login(client)
    await connect(client, "openai")
    drafted = await plan(client)
    assert drafted["limits"]["new_left"] == 0
    db_session.add_all(
        [
            Word(word=f"w{uuid.uuid4().hex[:10]}", translation="释义", tags=["cet4"])
            for _ in range(4)
        ]
    )
    await db_session.commit()
    assert (
        await client.put("/vocab/book", json={"book_id": "cet4", "daily_new": 3})
    ).status_code == 204
    conversation = (await daily(client))["id"]
    args = {"review": 0, "new_words": 10, "practice": True, "reading": False, "writing": False}
    script.replies = [[tool_call("propose_daily_plan", **args)], "Here you go."]

    _, events, _ = await send(client, conversation, "Add some new words.")

    (card,) = kinds(events, "card")
    assert card["params"]["choice"]["new_words"] == 3
    assert card["params"]["limits"]["new_left"] == 3
    assert (await client.post(f"/cards/{card['id']}/apply", json={})).status_code == 200
    now = await plan(client)
    assert now["limits"]["new_left"] == 3 and now["choice"]["new_words"] == 3
    assert (await client.post(f"/cards/{card['id']}/undo")).status_code == 200
    back = await plan(client)
    assert back["limits"]["new_left"] == 0 and back["choice"] == drafted["choice"]
