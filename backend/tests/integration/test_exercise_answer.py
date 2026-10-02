"""Answering practice items: grading, attempts, evidence, mastery, set status (ADR 0021 §6)."""

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise import answer as answering
from app.adaptive.exercise.answer import (
    ExerciseNotFoundError,
    GradingFailedError,
    NotAnswerableError,
)
from app.adaptive.exercise.formats import (
    ChoiceResponse,
    FindFixResponse,
    Response,
    TextResponse,
    parse_body,
)
from app.adaptive.exercise.grader import Graded, OtherMistake
from app.adaptive.exercise.grading import InvalidResponseError
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.agents.exercise_graph import ModelReply, StructuredCall
from app.db.models import (
    Attempt,
    Exercise,
    ExerciseSet,
    KCEvidence,
    KCMastery,
    User,
    UserProfile,
)

RULES, CATALOG = get_rules(), get_grammar_catalog()
KC = "g.present_simple_third_person"
OTHER = next(kc.id for kc in CATALOG.kcs if kc.id != KC)

ITEMS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "choice4": (
        {"stem": "He ___ here.", "options": ["lives", "live", "living", "is live"]},
        {"correct": "lives", "explanation": "Third person takes -s."},
    ),
    "translate": (
        {"source": "她走路上班。"},
        {"accepted": ["She walks to work."], "explanation": "Third person takes -s."},
    ),
    "find_fix": (
        {"segments": ["He ", "go ", "to work."]},
        {"wrong_segment": 1, "accepted": ["goes "], "explanation": "Third person takes -s."},
    ),
}


class FakeGrader:
    def __init__(self, graded: Graded | Exception) -> None:
        self.graded = graded
        self.calls: list[Sequence[BaseMessage]] = []

    async def __call__(
        self, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        assert schema is Graded
        self.calls.append(messages)
        if isinstance(self.graded, Exception):
            raise self.graded
        return ModelReply(self.graded, "fake:grader")


async def never(messages: Sequence[BaseMessage], schema: type[BaseModel]) -> ModelReply:
    raise AssertionError("code should have graded this")


async def learner(session: AsyncSession, explain_in: str | None = None) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    if explain_in:
        session.add(UserProfile(user_id=user.id, explanation_language=explain_in))
    await session.commit()
    return user.id


async def a_set(
    session: AsyncSession, user_id: uuid.UUID, formats: Sequence[str], status: str = "ready"
) -> list[int]:
    exercise_set = ExerciseSet(
        user_id=user_id,
        origin="dashboard",
        status=status,
        kc_plan=[{"kc_id": KC, "format": f, "difficulty": 0.0} for f in formats],
    )
    session.add(exercise_set)
    await session.flush()
    ids = []
    for position, fmt in enumerate(formats):
        content, key = ITEMS[fmt]
        body = parse_body(fmt, content, key)
        item = Exercise(
            user_id=user_id,
            set_id=exercise_set.id,
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


async def submit(
    session: AsyncSession,
    user_id: uuid.UUID,
    exercise_id: int,
    response: Response,
    grade_call: StructuredCall | None = never,
) -> answering.Answered:
    return await answering.answer(
        session,
        user_id,
        exercise_id,
        response,
        grade_call=grade_call,
        rules=RULES,
        catalog=CATALOG,
        latency_ms=1200,
    )


async def evidence(session: AsyncSession, user_id: uuid.UUID) -> list[KCEvidence]:
    rows = await session.scalars(
        select(KCEvidence).where(KCEvidence.user_id == user_id).order_by(KCEvidence.id)
    )
    return list(rows)


async def set_of(session: AsyncSession, exercise_id: int) -> ExerciseSet:
    session.expire_all()
    item = await session.get(Exercise, exercise_id)
    assert item is not None
    exercise_set = await session.get(ExerciseSet, item.set_id)
    assert exercise_set is not None
    return exercise_set


async def attempts(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Attempt)) or 0


async def test_a_right_choice_is_one_recognition_success(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    first, _ = await a_set(db_session, user_id, ["choice4", "choice4"])
    result = await submit(db_session, user_id, first, ChoiceResponse(choice="lives"))
    assert result.correct and not result.repeated and not result.set_done
    assert result.feedback["explanation"] == "Third person takes -s."
    assert result.feedback["model"] is None
    [row] = await evidence(db_session, user_id)
    assert (row.kc_id, row.correct, row.evidence, row.source, row.format) == (
        KC,
        True,
        "recognition",
        "exercise",
        "choice4",
    )
    assert row.attempt_id == result.attempt_id and row.error_type is None
    exercise_set = await set_of(db_session, first)
    assert exercise_set.status == "in_progress" and exercise_set.started_at is not None
    mastery = await db_session.get(KCMastery, (user_id, KC))
    assert mastery is not None and mastery.observations == 1


async def test_a_wrong_choice_records_the_mistake(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    [item] = await a_set(db_session, user_id, ["choice4"])
    result = await submit(db_session, user_id, item, ChoiceResponse(choice="live"))
    assert not result.correct
    [row] = await evidence(db_session, user_id)
    assert (row.correct, row.error_type, row.severity) == (False, "wrong_choice", "medium")
    assert (row.original, row.correction) == ("live", "lives")


async def test_only_the_first_answer_counts(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    item, _ = await a_set(db_session, user_id, ["choice4", "choice4"])
    first = await submit(db_session, user_id, item, ChoiceResponse(choice="live"))
    again = await submit(db_session, user_id, item, ChoiceResponse(choice="lives"))
    assert again.repeated and again.attempt_id == first.attempt_id and not again.correct
    assert await attempts(db_session) == 1
    assert len(await evidence(db_session, user_id)) == 1


async def test_an_open_answer_goes_to_the_model(db_session: AsyncSession) -> None:
    user_id = await learner(db_session, explain_in="en")
    [item] = await a_set(db_session, user_id, ["translate"])
    grader = FakeGrader(
        Graded(
            correct=False,
            explanation="Add -s after she.",
            corrected="She walks to the work.",
            other_mistakes=[
                OtherMistake(
                    kc_id=OTHER,
                    error_type="addition",
                    severity="low",
                    original="the work",
                    correction="work",
                ),
                # The tested KC: the verdict covers it, no second row.
                OtherMistake(
                    kc_id=KC,
                    error_type="wrong_form",
                    severity="medium",
                    original="walk",
                    correction="walks",
                ),
            ],
        )
    )
    result = await submit(
        db_session, user_id, item, TextResponse(text="She walk to the work."), grader
    )
    assert "Write the explanation in: English" in str(grader.calls[0][1].content)
    assert not result.correct and result.set_done
    assert result.feedback["model"] == "fake:grader"
    assert result.feedback["corrected"] == "She walks to the work."
    assert [m["kc_id"] for m in result.feedback["other_mistakes"]] == [OTHER]
    target, other = await evidence(db_session, user_id)
    assert (target.kc_id, target.evidence, target.correct) == (KC, "production", False)
    assert (target.original, target.correction) == (
        "She walk to the work.",
        "She walks to the work.",
    )
    assert (other.kc_id, other.error_type, other.severity) == (OTHER, "addition", "low")
    assert other.format == "translate" and other.attempt_id == result.attempt_id
    exercise_set = await set_of(db_session, item)
    assert exercise_set.status == "done" and exercise_set.finished_at is not None


async def test_an_open_answer_matching_a_reference_needs_no_model(
    db_session: AsyncSession,
) -> None:
    user_id = await learner(db_session)
    [item] = await a_set(db_session, user_id, ["translate"])
    result = await submit(db_session, user_id, item, TextResponse(text="she walks to work"))
    assert result.correct
    [row] = await evidence(db_session, user_id)
    assert (row.evidence, row.correct) == ("production", True)


@pytest.mark.parametrize("grade_call", [FakeGrader(RuntimeError("down")), None])
async def test_a_failed_grading_stores_nothing(
    db_session: AsyncSession, grade_call: StructuredCall | None
) -> None:
    user_id = await learner(db_session)
    [item] = await a_set(db_session, user_id, ["translate"])
    with pytest.raises(GradingFailedError):
        await submit(db_session, user_id, item, TextResponse(text="She walk."), grade_call)
    assert await attempts(db_session) == 0
    assert (await set_of(db_session, item)).status == "ready"
    # The learner submits again once the model is back.
    result = await submit(
        db_session,
        user_id,
        item,
        TextResponse(text="She walk."),
        FakeGrader(Graded(correct=False, explanation="e")),
    )
    assert not result.repeated


async def test_find_fix_on_the_wrong_piece_is_one_recognition_miss(
    db_session: AsyncSession,
) -> None:
    user_id = await learner(db_session)
    [item] = await a_set(db_session, user_id, ["find_fix"])
    await submit(db_session, user_id, item, FindFixResponse(segment=2, fix="to the work."))
    [row] = await evidence(db_session, user_id)
    assert (row.evidence, row.correct) == ("recognition", False)
    assert row.original == "He go to the work." and row.correction == "He goes to work."


async def test_find_fix_with_a_new_fix_asks_the_model(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    [item] = await a_set(db_session, user_id, ["find_fix"])
    grader = FakeGrader(Graded(correct=True, explanation="Also fine."))
    result = await submit(
        db_session, user_id, item, FindFixResponse(segment=1, fix="walks "), grader
    )
    assert result.correct and len(grader.calls) == 1
    spotted, fixed = await evidence(db_session, user_id)
    assert (spotted.evidence, spotted.correct) == ("recognition", True)
    assert (fixed.evidence, fixed.correct) == ("production", True)


async def test_answers_that_do_not_fit_are_refused(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    item, closed = await a_set(db_session, user_id, ["choice4", "choice4"])
    stranger = await learner(db_session)
    with pytest.raises(InvalidResponseError):
        await submit(db_session, user_id, item, ChoiceResponse(choice="lived"))
    with pytest.raises(ExerciseNotFoundError):
        await submit(db_session, stranger, item, ChoiceResponse(choice="lives"))
    exercise_set = await set_of(db_session, item)
    exercise_set.status = "failed"
    await db_session.commit()
    with pytest.raises(NotAnswerableError):
        await submit(db_session, user_id, closed, ChoiceResponse(choice="lives"))
    assert await attempts(db_session) == 0


async def test_a_rejected_item_cannot_be_answered(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    [item] = await a_set(db_session, user_id, ["choice4"])
    row = await db_session.get(Exercise, item)
    assert row is not None
    row.status = "rejected"
    await db_session.commit()
    with pytest.raises(ExerciseNotFoundError):
        await submit(db_session, user_id, item, ChoiceResponse(choice="lives"))


async def report(session: AsyncSession, user_id: uuid.UUID, exercise_id: int) -> bool:
    return await answering.report(session, user_id, exercise_id, rules=RULES, catalog=CATALOG)


async def test_reporting_an_answered_item_drops_its_evidence(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    answered, waiting = await a_set(db_session, user_id, ["choice4", "choice4"])
    await submit(db_session, user_id, answered, ChoiceResponse(choice="live"))
    assert not await report(db_session, user_id, answered)
    assert await evidence(db_session, user_id) == []
    assert await db_session.get(KCMastery, (user_id, KC)) is None
    assert await attempts(db_session) == 1  # the answer itself is kept
    assert not await report(db_session, user_id, answered)  # again: nothing changes
    # Reporting the last unanswered item finishes the set.
    assert await report(db_session, user_id, waiting)
    assert (await set_of(db_session, waiting)).status == "done"
    with pytest.raises(NotAnswerableError):
        await submit(db_session, user_id, waiting, ChoiceResponse(choice="lives"))
