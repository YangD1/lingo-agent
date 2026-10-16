"""Lessons of the grammar course (ADR 0044 §5): started from the course, taught by the
tutor with its tools and the lesson's material, and tested out of without a chat turn."""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ExerciseSet
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
from tests.integration.test_quiz_tools import answer
from tests.integration.test_workspace_tools import results

# With no placement test, the course opens on its first lesson; the third person -s
# builds on word order, so it is locked until that one is passed.
OPEN = "g.word_order_svo"
LOCKED = "g.present_simple_third_person"


@pytest.fixture(autouse=True)
def no_generation(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """Quiz sets stay generating: the fake chat model cannot write exercises."""
    monkeypatch.setattr(app.state.practice_worker, "_spawn", lambda *a, **k: None)


async def ready(client: AsyncClient) -> None:
    await login(client)
    await connect(client, "openai")


async def start(client: AsyncClient, kc_id: str, expect: int = 201) -> dict[str, Any]:
    response = await client.post(f"/course/lessons/{kc_id}", json={"locale": "en"})
    assert response.status_code == expect, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_a_lesson_is_started_once_and_continued(client: AsyncClient) -> None:
    await ready(client)
    course = (await client.get("/course")).json()
    states = {lesson["kc_id"]: lesson["state"] for lesson in course["lessons"]}
    assert (states[OPEN], states[LOCKED]) == ("available", "locked")

    first = (await start(client, OPEN))["conversation"]
    assert (first["purpose"], first["focus_kc"]["id"]) == ("lesson", OPEN)
    assert first["title"].startswith("Lesson: ")
    assert (await start(client, OPEN, expect=200))["conversation"]["id"] == first["id"]
    # Opening a lesson starts it.
    course = (await client.get("/course")).json()
    assert next(x for x in course["lessons"] if x["kc_id"] == OPEN)["state"] == "learning"
    # Practice on the same point is a conversation of its own.
    practice = await client.post("/conversations", json={"focus_kc_id": OPEN})
    assert practice.status_code == 201 and practice.json()["id"] != first["id"]

    locked = await client.post(f"/course/lessons/{LOCKED}")
    assert (locked.status_code, locked.json()["detail"]["code"]) == (409, "lesson_locked")
    missing = await client.post("/course/lessons/g.no_such_kc")
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "lesson_not_found")


async def test_the_tutor_opens_the_lesson_with_its_material_and_tools(
    client: AsyncClient,
    script: Script,  # noqa: F811
    usage_records: list[UsageRecord],  # noqa: F811
) -> None:
    await ready(client)
    conversation = (await start(client, OPEN))["conversation"]["id"]
    script.replies = [
        [tool_call("give_quiz", kc_id=OPEN, purpose="check", asked=False)],
        "Have a go at the card.",
    ]

    response = await client.post(f"/conversations/{conversation}/opening")
    assert response.status_code == 200, response.text
    events = parse_sse(response.text)

    (card,) = kinds(events, "card")
    assert (card["kind"], card["params"]["purpose"]) == ("quiz", "check")
    offered, messages = script.calls[0]
    assert offered is not None and "give_quiz" in offered
    prompt = system_text(messages)
    assert "a lesson of the grammar course" in prompt
    assert "<lesson>" in prompt and "- Lesson 1: " in prompt
    assert "- State: in progress, not passed yet" in prompt
    assert "- Pass quizzes taken: none yet" in prompt
    assert isinstance(messages[-1], HumanMessage) and "opened this lesson" in messages[-1].text
    # The reply after the tool call is recorded like any other (ADR 0015 §7).
    assert [r.task for r in usage_records] == ["lesson_opening", "chat_tools"]
    (load,) = [a for a in await activity(client, conversation) if a["name"] == "load_context"]
    assert load["summary"]["practice_kc"] == OPEN


async def test_cards_stay_on_the_lesson_and_its_prerequisites(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await ready(client)
    conversation = (await start(client, OPEN))["conversation"]["id"]
    script.replies = [
        [
            tool_call("give_quiz", kc_id=LOCKED, purpose="check", asked=False),
            tool_call("suggest_link", kind="course"),
        ],
        "Let's stay on word order.",
    ]
    # Long enough to be classified as writing in free chat: a lesson never hands it on.
    text = "I want to practise word order. " * 15

    status, events, _ = await send(client, conversation, text)

    assert status == 200
    assert [c["kind"] for c in kinds(events, "card")] == ["link"]
    quiz, link = (m.text for m in results(script)[-2:])
    assert "is not a grammar point of this conversation" in quiz
    assert link.startswith("Card shown")
    assert len(script.calls) == 2  # no route call


async def test_test_out_shows_a_pass_quiz_without_a_turn(
    client: AsyncClient,
    db_session: AsyncSession,
    script: Script,  # noqa: F811
) -> None:
    await ready(client)

    response = await client.post(f"/course/lessons/{LOCKED}/test-out")

    assert response.status_code == 201, response.text
    body = response.json()
    conversation, card = body["conversation"], body["card"]
    assert (conversation["purpose"], conversation["focus_kc"]["id"]) == ("lesson", LOCKED)
    assert (card["kind"], card["status"], card["params"]["purpose"]) == ("quiz", "info", "quiz")
    assert card["turn_id"].startswith("test-out-")
    assert script.calls == []  # no chat model call
    (row,) = await db_session.scalars(select(ExerciseSet).where(ExerciseSet.origin == "quiz"))
    assert (str(row.id), row.quiz_purpose, row.focus_kc_id) == (
        card["params"]["set_id"],
        "quiz",
        LOCKED,
    )
    assert [c["id"] for c in await cards(client, conversation["id"])] == [card["id"]]

    # The same lesson again (task 94): no daily cap; the unfinished quiz comes back.
    for _ in range(3):
        again = await client.post(f"/course/lessons/{LOCKED}/test-out")
        assert again.status_code == 200
        assert again.json()["conversation"]["id"] == conversation["id"]
        assert again.json()["card"]["params"]["set_id"] == card["params"]["set_id"]


async def test_the_lesson_knows_how_the_pass_quiz_went(
    client: AsyncClient,
    db_session: AsyncSession,
    script: Script,  # noqa: F811
) -> None:
    await ready(client)
    tested = (await client.post(f"/course/lessons/{OPEN}/test-out")).json()
    conversation = tested["conversation"]["id"]
    (row,) = await db_session.scalars(select(ExerciseSet).where(ExerciseSet.origin == "quiz"))
    await answer(db_session, row.id, [True, True, False, True, False])
    script.replies = ["Let's look at the two you missed."]

    await send(client, conversation, "How did I do?")

    prompt = system_text(script.calls[0][1])
    assert "- Pass quizzes taken: 1; the latest: 60% right" in prompt
    assert 'answered "past", expected "he is one person"' in prompt
    assert "- State: in progress, not passed yet" in prompt
    lesson = await db_session.scalar(select(Conversation).where(Conversation.purpose == "lesson"))
    assert lesson is not None and lesson.focus_kc_id == OPEN
