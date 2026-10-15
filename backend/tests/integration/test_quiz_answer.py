"""Answering understanding checks (ADR 0044 §3): graded and stored, but no evidence,
no ability step, no mastery row; `explain` gets feedback from its own prompt."""

import uuid
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise.formats import ChoiceResponse, TextResponse, parse_body
from app.adaptive.exercise.grader import Explained
from app.agents.exercise_graph import ModelReply
from app.db.models import Attempt, Exercise, ExerciseSet, KCMastery, SkillEstimate
from tests.integration.test_exercise_answer import KC, evidence, learner, set_of, submit

CHECKS = {
    "concept_choice": (
        {"question": "Why 'lives'?", "options": ["he is one person", "past", "plural", "polite"]},
        {"correct": "he is one person", "explanation": "Third person singular takes -s."},
    ),
    "explain": (
        {"question": "When does a verb take -s?"},
        {"key_points": ["he, she, it", "present simple"], "explanation": "With he, she, it."},
    ),
}


async def a_check(session: AsyncSession, user_id: uuid.UUID, formats: list[str]) -> list[int]:
    check = ExerciseSet(
        user_id=user_id,
        origin="quiz",
        quiz_purpose="check",
        status="ready",
        kc_plan=[],
        focus_kc_id=KC,
    )
    session.add(check)
    await session.flush()
    ids = []
    for position, fmt in enumerate(formats):
        body = parse_body(fmt, *CHECKS[fmt])
        item = Exercise(
            user_id=user_id,
            set_id=check.id,
            position=position,
            kc_id=KC,
            format=fmt,
            content=body.content.model_dump(mode="json"),
            answer=body.answer.model_dump(mode="json"),
            difficulty=0.0,
            status="ok",
        )
        session.add(item)
        await session.flush()
        ids.append(item.id)
    await session.commit()
    return ids


class FakeExplainer:
    def __init__(self, explained: Explained) -> None:
        self.explained = explained
        self.calls: list[Sequence[BaseMessage]] = []

    async def __call__(
        self, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        assert schema is Explained
        self.calls.append(messages)
        return ModelReply(self.explained, "fake:grader")


def text(message: BaseMessage) -> Any:
    return message.content


async def test_checks_leave_the_learner_model_alone(db_session: AsyncSession) -> None:
    user_id = await learner(db_session, explain_in="zh")
    choice, explain = await a_check(db_session, user_id, ["concept_choice", "explain"])

    wrong = await submit(db_session, user_id, choice, ChoiceResponse(choice="past"))
    assert not wrong.correct
    assert wrong.feedback["explanation"] == "Third person singular takes -s."

    grader = FakeExplainer(
        Explained(verdict="partly", missing=["present simple", " "], feedback="  差一点。 ")
    )
    partly = await submit(
        db_session, user_id, explain, TextResponse(text="he 和 she 的时候"), grader
    )
    assert not partly.correct and partly.set_done
    assert partly.feedback["verdict"] == "partly"
    assert partly.feedback["missing"] == ["present simple"]
    assert partly.feedback["explanation"] == "差一点。"
    [system, human] = grader.calls[0]
    assert "explanation of an English grammar rule" in text(system)
    assert "Simplified Chinese" in text(human) and "he 和 she 的时候" in text(human)
    assert "- he, she, it" in text(human)

    assert await evidence(db_session, user_id) == []
    assert await db_session.get(KCMastery, (user_id, KC)) is None
    rows = await db_session.scalars(select(SkillEstimate).where(SkillEstimate.user_id == user_id))
    assert list(rows) == []
    stored = await db_session.scalars(select(Attempt.correct).order_by(Attempt.id))
    assert [c for c in stored][-2:] == [False, False]
    assert (await set_of(db_session, choice)).status == "done"
    assert partly.quiz


async def test_a_right_explanation_is_correct(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    [explain] = await a_check(db_session, user_id, ["explain"])
    grader = FakeExplainer(Explained(verdict="right", feedback="对。"))
    result = await submit(db_session, user_id, explain, TextResponse(text="he she it"), grader)
    assert result.correct and result.feedback["missing"] == []
