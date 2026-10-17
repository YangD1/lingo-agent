"""A reply that gives away an unanswered pass-quiz answer (task 95.3): the item is
marked, its answer counts as wrong and writes no evidence."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import course
from app.adaptive.exercise.formats import ChoiceResponse, parse_body
from app.db.models import Exercise, ExerciseSet
from tests.integration.test_chat_tools import (
    Script,
    _clear_caches,  # noqa: F401
    activity,
    ready,
    send,
    system_text,
    tool_call,
)
from tests.integration.test_exercise_answer import ITEMS, KC, evidence, learner, submit
from tests.integration.test_quiz_tools import quiz_sets
from tests.integration.test_workspace_tools import script as tool_script

script = tool_script


@pytest.fixture(autouse=True)
def no_generation(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state.practice_worker, "_spawn", lambda *a, **k: None)


async def fill(db: AsyncSession, set_id: uuid.UUID, formats: list[str]) -> list[int]:
    row = await db.get(ExerciseSet, set_id)
    assert row is not None
    ids = []
    for position, fmt in enumerate(formats):
        body = parse_body(fmt, *ITEMS[fmt])
        item = Exercise(
            user_id=row.user_id,
            set_id=set_id,
            position=position,
            kc_id=KC,
            format=fmt,
            content=body.content.model_dump(mode="json"),
            answer=body.answer.model_dump(mode="json"),
            difficulty=0.0,
            status="ok",
        )
        db.add(item)
        await db.flush()
        ids.append(item.id)
    row.status = "in_progress"
    await db.commit()
    return ids


async def revealed_ids(db: AsyncSession) -> list[int]:
    db.expire_all()
    return list(await db.scalars(select(Exercise.id).where(Exercise.revealed_at.is_not(None))))


async def quiz_with(
    client: AsyncClient, db: AsyncSession, script: Script, purpose: str
) -> tuple[str, list[int]]:
    conversation = await ready(client)
    script.replies = [[tool_call("give_quiz", kc_id=KC, purpose=purpose, asked=True)], "Go."]
    await send(client, conversation, "Quiz me.")
    (row,) = await quiz_sets(db)
    return conversation, await fill(db, row.id, ["choice4", "translate"])


async def test_a_reply_giving_an_answer_away_marks_that_item(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation, (choice, _) = await quiz_with(client, db_session, script, "quiz")
    script.replies = ["第一题主语是 he 所以选 lives。"]

    await send(client, conversation, "第一题怎么做")

    assert await revealed_ids(db_session) == [choice]
    (step,) = [a for a in await activity(client, conversation) if a["name"] == "quiz_reveal"]
    assert step["kind"] == "background"
    assert step["summary"] == {"kc_id": KC, "items": 1}

    script.calls.clear()
    script.replies = ["Try the next one."]
    await send(client, conversation, "OK")
    prompt = system_text(script.calls[0][1])
    assert "you gave its answer away, so it counts as wrong whatever they answer" in prompt
    assert prompt.count("you gave its answer away") == 1


async def test_a_reply_without_answers_marks_nothing(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation, _ = await quiz_with(client, db_session, script, "quiz")
    script.replies = ["想想主语是谁、动词要不要加 -s。"]
    await send(client, conversation, "第一题怎么做")
    assert await revealed_ids(db_session) == []
    assert "quiz_reveal" not in [a["name"] for a in await activity(client, conversation)]


async def test_an_understanding_check_is_not_looked_at(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    check, _ = await quiz_with(client, db_session, script, "check")
    script.replies = ["选 lives。"]
    await send(client, check, "第一题怎么做")
    assert await revealed_ids(db_session) == []


async def test_a_revealed_item_counts_as_wrong_and_writes_no_evidence(
    db_session: AsyncSession,
) -> None:
    user_id = await learner(db_session)
    quiz = ExerciseSet(
        user_id=user_id,
        origin="quiz",
        quiz_purpose="quiz",
        status="ready",
        kc_plan=[],
        focus_kc_id=KC,
    )
    db_session.add(quiz)
    await db_session.flush()
    given, fair = await fill(db_session, quiz.id, ["choice4", "choice4"])
    item = await db_session.get(Exercise, given)
    assert item is not None
    item.revealed_at = item.created_at
    await db_session.commit()

    first = await submit(db_session, user_id, given, ChoiceResponse(choice="lives"))
    assert first.correct  # the learner still sees they got it right
    assert await evidence(db_session, user_id) == []

    await submit(db_session, user_id, fair, ChoiceResponse(choice="lives"))
    assert len(await evidence(db_session, user_id)) == 1
    assert await course.quiz_scores(db_session, user_id) == {KC: 0.5}
