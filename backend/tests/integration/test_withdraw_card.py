"""withdraw_card (ADR 0049): the tutor takes back a card it showed by mistake; a quiz
card's set stops being written. Refused once the learner has acted on the card."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExerciseSet
from tests.integration.test_chat_tools import (
    Script,
    _clear_caches,  # noqa: F401
    activity,
    cards,
    kinds,
    ready,
    send,
    system_text,
    tool_call,
)
from tests.integration.test_quiz_tools import KC, answer
from tests.integration.test_workspace_tools import script as tool_script

script = tool_script


@pytest.fixture(autouse=True)
def stopped(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Sets stay generating (the fake chat model can't write exercises); the sets the
    tools ask the worker to stop."""
    monkeypatch.setattr(app.state.practice_worker, "_spawn", lambda *a, **k: None)
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(app.state.practice_worker, "cancel", calls.append)
    return calls


def result(script: Script, call: dict[str, Any]) -> ToolMessage:
    """What the tools told the model about `call`, as the last model call saw it."""
    (found,) = [
        m
        for m in script.calls[-1][1]
        if isinstance(m, ToolMessage) and m.tool_call_id == call["id"]
    ]
    return found


async def quiz_set(db: AsyncSession) -> ExerciseSet:
    row = await db.scalar(select(ExerciseSet).where(ExerciseSet.origin == "quiz"))
    assert row is not None
    await db.refresh(row)
    return row


async def test_a_quiz_withdrawn_in_the_same_turn_stops_its_set(
    client: AsyncClient, db_session: AsyncSession, script: Script, stopped: list[uuid.UUID]
) -> None:
    conversation = await ready(client)
    quiz = tool_call("give_quiz", kc_id=KC, purpose="quiz", asked=True)
    withdraw = tool_call("withdraw_card", card=quiz["id"], reason="主题弄错了")
    script.replies = [[quiz], [withdraw], "我把那张卡撤回了。"]

    status, events, _ = await send(client, conversation, "Test me, please.")

    assert status == 200
    shown, taken_back = kinds(events, "card")
    assert shown["id"] == taken_back["id"]
    assert (shown["status"], taken_back["status"]) == ("info", "withdrawn")
    assert taken_back["withdrawn_reason"] == "主题弄错了"
    row = await quiz_set(db_session)
    assert (row.status, row.error_code) == ("failed", "withdrawn")
    assert stopped == [row.id]
    # The tutor names the card by the id its result gives.
    assert result(script, quiz).text.startswith(f"(card {quiz['id']})")
    took = result(script, withdraw)
    assert took.status == "success" and "Card withdrawn" in took.text
    assert [c["status"] for c in await cards(client, conversation)] == ["withdrawn"]
    steps = [a["name"] for a in await activity(client, conversation)]
    assert {"give_quiz", "withdraw_card"} <= set(steps)

    # Later turns see it withdrawn; withdrawing again changes nothing.
    again = tool_call("withdraw_card", card=quiz["id"], reason="主题弄错了")
    script.replies = [[again], "Done."]
    await send(client, conversation, "ok")
    prompt = system_text(script.calls[-2][1])
    assert f"[card {quiz['id']}]" in prompt and "you withdrew it" in prompt
    assert result(script, again).status == "success"
    assert stopped == [row.id]


async def test_an_answered_quiz_stays(
    client: AsyncClient, db_session: AsyncSession, script: Script, stopped: list[uuid.UUID]
) -> None:
    conversation = await ready(client)
    quiz = tool_call("give_quiz", kc_id=KC, purpose="quiz", asked=True)
    script.replies = [[quiz], "Try the card."]
    await send(client, conversation, "Test me, please.")
    row = await quiz_set(db_session)
    await answer(db_session, row.id, [True])

    withdraw = tool_call("withdraw_card", card=quiz["id"], reason="wrong")
    script.replies = [[withdraw], "Sorry."]
    _, events, _ = await send(client, conversation, "That's the wrong topic.")

    assert kinds(events, "card") == []
    refused = result(script, withdraw)
    assert refused.status == "error" and "started answering" in refused.text
    assert (await quiz_set(db_session)).status == "done"
    assert stopped == []


async def test_a_waiting_proposal_can_be_withdrawn_a_confirmed_one_cannot(
    client: AsyncClient, script: Script
) -> None:
    conversation = await ready(client)
    first = tool_call("propose_word_book", book_id="cet4")
    second = tool_call("propose_learning_goal", goal="Pass IELTS")
    script.replies = [[first, second], "Two cards."]
    await send(client, conversation, "Help me set things up.")
    book, goal = await cards(client, conversation)
    assert (await client.post(f"/cards/{goal['id']}/apply")).status_code == 200

    take_book = tool_call("withdraw_card", card=first["id"], reason="not what you asked")
    take_goal = tool_call("withdraw_card", card=second["id"], reason="not what you asked")
    script.replies = [[take_book, take_goal], "Took one back."]
    _, events, _ = await send(client, conversation, "Never mind.")

    (withdrawn,) = kinds(events, "card")
    assert (withdrawn["id"], withdrawn["status"]) == (book["id"], "withdrawn")
    assert result(script, take_book).status == "success"
    refused = result(script, take_goal)
    assert refused.status == "error" and "already applied" in refused.text
    # The learner can no longer confirm what was taken back.
    response = await client.post(f"/cards/{book['id']}/apply")
    assert response.status_code == 409
    assert (await client.get("/vocab")).json()["book_id"] is None


async def test_only_this_conversations_cards(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    proposal = tool_call("propose_word_book", book_id="cet4")
    script.replies = [[proposal], "A card."]
    await send(client, conversation, "Suggest a book.")
    other = (await client.post("/conversations", json={})).json()["id"]

    missing_call = tool_call("withdraw_card", card=proposal["id"], reason="wrong")
    invalid_call = tool_call("withdraw_card", card=proposal["id"], reason="")
    script.replies = [[missing_call, invalid_call], "Hm."]
    await send(client, other, "Take the book back.")

    missing, invalid = result(script, missing_call), result(script, invalid_call)
    assert missing.status == "error" and "no card" in missing.text
    assert invalid.status == "error" and "reason" in invalid.text
    assert [c["status"] for c in await cards(client, conversation)] == ["proposed"]


async def test_a_quiz_shown_on_another_card_keeps_its_set(
    client: AsyncClient, db_session: AsyncSession, script: Script, stopped: list[uuid.UUID]
) -> None:
    """Task 94: asked again, the unfinished set comes back on a new card; withdrawing
    that card leaves the set to the first one."""
    conversation = await ready(client)
    script.replies = [[tool_call("give_quiz", kc_id=KC, purpose="quiz", asked=True)], "Try it."]
    await send(client, conversation, "Quiz me.")
    again = tool_call("give_quiz", kc_id=KC, purpose="quiz", asked=True)
    withdraw = tool_call("withdraw_card", card=again["id"], reason="上面那张就是")
    script.replies = [[again], [withdraw], "用上面那张就行。"]

    await send(client, conversation, "Quiz me again.")

    assert result(script, withdraw).status == "success"
    row = await quiz_set(db_session)
    assert row.status == "generating" and stopped == []
    statuses = sorted(c["status"] for c in await cards(client, conversation))
    assert statuses == ["info", "withdrawn"]
