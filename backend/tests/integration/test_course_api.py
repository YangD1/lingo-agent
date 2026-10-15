"""GET /course (ADR 0044 §2): the lessons in order with their states."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise.formats import parse_body
from app.db.models import Attempt, Exercise, ExerciseSet, User
from tests.integration.test_chat_send import login
from tests.integration.test_exercise_answer import ITEMS

FIRST = "g.word_order_svo"
SECOND = "g.be_present"


async def course(client: AsyncClient) -> dict[str, Any]:
    response = await client.get("/course")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def finished_quiz(db: AsyncSession, kc_id: str, answers: list[list[bool]]) -> None:
    """A done pass quiz on `kc_id`: one item per entry, with its answers in order."""
    user_id = await db.scalar(select(User.id).where(User.email == "learner@example.com"))
    assert user_id is not None
    quiz = ExerciseSet(
        user_id=user_id,
        origin="quiz",
        quiz_purpose="quiz",
        status="done",
        kc_plan=[],
        focus_kc_id=kc_id,
    )
    db.add(quiz)
    await db.flush()
    content, key = ITEMS["choice4"]
    body = parse_body("choice4", content, key)
    for position, tries in enumerate(answers):
        item = Exercise(
            user_id=user_id,
            set_id=quiz.id,
            position=position,
            kc_id=kc_id,
            format="choice4",
            content=body.content.model_dump(mode="json"),
            answer=body.answer.model_dump(mode="json"),
            difficulty=0.0,
            status="ok",
        )
        db.add(item)
        await db.flush()
        for correct in tries:
            db.add(Attempt(user_id=user_id, exercise_id=item.id, response={}, correct=correct))
    await db.commit()


async def test_a_new_learner_starts_at_lesson_one(client: AsyncClient) -> None:
    await login(client)
    body = await course(client)
    assert body["level"] is None
    assert body["current"] == FIRST
    assert body["pass_score"] == 0.8
    lessons = body["lessons"]
    assert len(lessons) == 119
    assert lessons[0] | {"p_mastery": None} == {
        "number": 1,
        "kc_id": FIRST,
        "name_en": lessons[0]["name_en"],
        "name_zh": lessons[0]["name_zh"],
        "cefr": "A1",
        "state": "available",
        "p_mastery": None,
        "quiz_score": None,
        "blocked_by": [],
    }
    assert {lesson["state"] for lesson in lessons} == {"available", "locked"}


async def test_a_quiz_scores_first_answers_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    # Four right first time, one right only on a second try: 0.8. Mastery stays at the
    # prior (no evidence was written), so the lesson is not passed yet.
    await finished_quiz(db_session, SECOND, [[True], [True], [True], [True], [False, True]])
    lessons = {lesson["kc_id"]: lesson for lesson in (await course(client))["lessons"]}
    assert lessons[SECOND]["quiz_score"] == 0.8
    assert lessons[SECOND]["state"] == "learning"
    assert lessons[FIRST]["quiz_score"] is None


async def test_needs_a_login(client: AsyncClient) -> None:
    assert (await client.get("/course")).status_code == 401
