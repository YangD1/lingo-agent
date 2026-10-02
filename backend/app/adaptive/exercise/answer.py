"""Answering a practice item: grade it, record it, update mastery (ADR 0021 §6).

Code grades what it can (`grading.grade`); the rest goes to `exercise_grade`. Only the
first answer to an item counts (Q34b): answering again returns the first result. If the
grading model fails, nothing is stored and the learner submits again (Q34d). The tested
KC gets one evidence row per observation (find_fix: recognition, then production when
the piece was right, Q34f); each other mistake the model found gets its own row (Q34e).
Each counted answer also moves the learner's grammar ability by Elo against the item's
difficulty (Q34c); item difficulties stay as they are (generated items are not
calibrated, bank items do not feed the shared placement statistics).

`answer` and `report` are each one unit of work and commit. No transaction stays open
across the model call: the item is read again, locked, before anything is written.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.elo import guess_for, update_ability
from app.adaptive.exercise.formats import (
    Choice4,
    ChoiceResponse,
    ExerciseBody,
    FindFix,
    FindFixResponse,
    Response,
    parse_body,
)
from app.adaptive.exercise.grader import Graded, Verdict, grade_messages, learner_answer, verdict
from app.adaptive.exercise.grading import Mark, grade, with_fix
from app.adaptive.exercise.inputs import ExplainIn
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog
from app.adaptive.mastery import refresh
from app.adaptive.rules import Rules
from app.agents.exercise_graph import StructuredCall
from app.db.models import Attempt, Exercise, ExerciseSet, KCEvidence, SkillEstimate, UserProfile

OPEN_SET = ("ready", "in_progress")


class ExerciseNotFoundError(LookupError):
    """No such item for this learner (or one the critic rejected, never shown)."""


class NotAnswerableError(ValueError):
    """The item was reported, or its set is not open for answers."""


class GradingFailedError(RuntimeError):
    """The grading model could not grade the answer; nothing was stored (Q34d)."""


@dataclass(frozen=True, slots=True)
class Answered:
    attempt_id: int
    correct: bool
    # As stored on the attempt: explanation, corrected answer, other mistakes, model.
    feedback: dict[str, Any]
    # The item was answered before: this is that answer's result, nothing was recorded.
    repeated: bool
    # This answer finished the set: time to generate the next one ahead.
    set_done: bool


async def _item(
    session: AsyncSession, user_id: uuid.UUID, exercise_id: int, *, lock: bool = False
) -> Exercise:
    query = select(Exercise).where(
        Exercise.id == exercise_id, Exercise.user_id == user_id, Exercise.status != "rejected"
    )
    item = await session.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise ExerciseNotFoundError(exercise_id)
    return item


async def _first_attempt(session: AsyncSession, exercise_id: int) -> Attempt | None:
    return await session.scalar(
        select(Attempt).where(Attempt.exercise_id == exercise_id).order_by(Attempt.id).limit(1)
    )


def _repeated(attempt: Attempt) -> Answered:
    return Answered(attempt.id, attempt.correct, attempt.feedback, repeated=True, set_done=False)


async def _open_set(session: AsyncSession, item: Exercise) -> ExerciseSet:
    if item.status == "reported":
        raise NotAnswerableError("the item was reported")
    exercise_set = await session.get(ExerciseSet, item.set_id)
    assert exercise_set is not None  # FK
    if exercise_set.status not in OPEN_SET:
        raise NotAnswerableError(f"the set is {exercise_set.status}")
    return exercise_set


async def _explain_in(session: AsyncSession, user_id: uuid.UUID) -> ExplainIn:
    language = await session.scalar(
        select(UserProfile.explanation_language).where(UserProfile.user_id == user_id)
    )
    return "en" if language == "en" else "zh"


def _given(body: ExerciseBody, response: Response) -> str:
    if isinstance(response, ChoiceResponse):
        return response.choice
    return learner_answer(body, response)


def _expected(body: ExerciseBody) -> str:
    if isinstance(body, Choice4):
        return body.answer.correct
    if isinstance(body, FindFix):
        fix = FindFixResponse(segment=body.answer.wrong_segment, fix=body.answer.accepted[0])
        return with_fix(body.content, fix)
    return body.answer.accepted[0]


async def _model_verdict(
    session: AsyncSession,
    user_id: uuid.UUID,
    item: Exercise,
    body: ExerciseBody,
    response: Response,
    grade_call: StructuredCall | None,
    catalog: GrammarCatalog,
) -> tuple[Verdict, str | None]:
    kc = catalog.get(item.kc_id)
    if grade_call is None or kc is None:
        raise GradingFailedError("no grading model" if kc else f"unknown KC {item.kc_id}")
    messages = grade_messages(body, kc, response, await _explain_in(session, user_id))
    # Don't hold a transaction open while the model thinks.
    await session.rollback()
    try:
        reply = await grade_call(messages, Graded)
    except Exception as exc:
        raise GradingFailedError(type(exc).__name__) from exc
    return verdict(cast(Graded, reply.output), kc, catalog), reply.model


async def _finish_if_done(session: AsyncSession, exercise_set: ExerciseSet, now: datetime) -> bool:
    """Mark the set done once every item still counting has an answer."""
    if exercise_set.status not in OPEN_SET:
        return False
    waiting = await session.scalar(
        select(func.count())
        .select_from(Exercise)
        .where(
            Exercise.set_id == exercise_set.id,
            Exercise.status == "ok",
            ~exists().where(Attempt.exercise_id == Exercise.id),
        )
    )
    if waiting:
        return False
    exercise_set.status = "done"
    exercise_set.finished_at = now
    return True


async def _update_ability(
    session: AsyncSession, user_id: uuid.UUID, item: Exercise, correct: bool, rules: Rules
) -> None:
    """One Elo step on the grammar ability; without one yet, start from the learner's
    level anchor, as practice planning does (`inputs.load`)."""
    row = await session.scalar(
        select(SkillEstimate)
        .where(SkillEstimate.user_id == user_id, SkillEstimate.skill == "grammar")
        .with_for_update()
    )
    if row is None:
        level = cast(
            CefrLevel | None,
            await session.scalar(
                select(UserProfile.cefr_level).where(UserProfile.user_id == user_id)
            ),
        )
        anchor = rules.difficulty.cefr_anchor[level or rules.practice.default_level]
        row = SkillEstimate(user_id=user_id, skill="grammar", rating=anchor, attempts=0)
        session.add(row)
    guess = guess_for(item.format, rules)
    row.rating = update_ability(row.rating, item.difficulty, correct, row.attempts, rules, guess)
    row.attempts += 1


def _start(exercise_set: ExerciseSet, now: datetime) -> None:
    if exercise_set.status == "ready":
        exercise_set.status = "in_progress"
        exercise_set.started_at = exercise_set.started_at or now


async def answer(
    session: AsyncSession,
    user_id: uuid.UUID,
    exercise_id: int,
    response: Response,
    *,
    grade_call: StructuredCall | None,
    rules: Rules,
    catalog: GrammarCatalog,
    latency_ms: int | None = None,
    now: datetime | None = None,
) -> Answered:
    """Grade and record the learner's first answer to an item; commits.

    Raises `ExerciseNotFoundError`, `NotAnswerableError`, `InvalidResponseError` (the
    answer does not fit the item) or `GradingFailedError`.
    """
    now = now or datetime.now(UTC)
    item = await _item(session, user_id, exercise_id)
    if (earlier := await _first_attempt(session, exercise_id)) is not None:
        return _repeated(earlier)
    await _open_set(session, item)
    body = parse_body(item.format, item.content, item.answer)
    code = grade(body, response)
    model_verdict: Verdict | None = None
    model: str | None = None
    if code.needs_model:
        model_verdict, model = await _model_verdict(
            session, user_id, item, body, response, grade_call, catalog
        )

    item = await _item(session, user_id, exercise_id, lock=True)
    if (earlier := await _first_attempt(session, exercise_id)) is not None:
        return _repeated(earlier)  # answered while the model was grading this one
    exercise_set = await _open_set(session, item)

    marks = code.marks
    if model_verdict is not None:
        marks = (*marks, Mark("production", model_verdict.correct))
    correct = all(m.correct for m in marks)
    others = model_verdict.other_mistakes if model_verdict else ()
    feedback: dict[str, Any] = {
        "explanation": model_verdict.explanation if model_verdict else body.answer.explanation,
        "corrected": model_verdict.corrected if model_verdict else None,
        "other_mistakes": [m.model_dump(mode="json") for m in others],
        "model": model,
    }
    attempt = Attempt(
        user_id=user_id,
        exercise_id=item.id,
        response=response.model_dump(mode="json"),
        correct=correct,
        latency_ms=latency_ms,
        feedback=feedback,
        created_at=now,
    )
    session.add(attempt)
    await session.flush()

    given = _given(body, response)
    expected = (model_verdict.corrected if model_verdict else None) or _expected(body)
    for mark in marks:
        session.add(
            _evidence(
                attempt,
                item,
                kc_id=item.kc_id,
                correct=mark.correct,
                evidence=mark.evidence,
                # The verdict on the tested KC has two levels only (ADR 0021 §6).
                mistake=None if mark.correct else ("wrong_choice", "medium", given, expected),
            )
        )
    for other in others:
        session.add(
            _evidence(
                attempt,
                item,
                kc_id=other.kc_id,
                correct=False,
                evidence="production",
                mistake=(other.error_type, other.severity, other.original, other.correction),
            )
        )
    await _update_ability(session, user_id, item, correct, rules)
    _start(exercise_set, now)
    set_done = await _finish_if_done(session, exercise_set, now)
    await session.flush()
    await refresh(
        session, user_id, {item.kc_id, *(o.kc_id for o in others)}, rules=rules, catalog=catalog
    )
    await session.commit()
    return Answered(attempt.id, correct, feedback, repeated=False, set_done=set_done)


def _evidence(
    attempt: Attempt,
    item: Exercise,
    *,
    kc_id: str,
    correct: bool,
    evidence: str,
    mistake: tuple[str, str, str, str] | None,
) -> KCEvidence:
    error_type, severity, original, correction = mistake or (None, None, None, None)
    return KCEvidence(
        user_id=attempt.user_id,
        kc_id=kc_id,
        correct=correct,
        evidence=evidence,
        source="exercise",
        format=item.format,
        attempt_id=attempt.id,
        error_type=error_type,
        severity=severity,
        original=original,
        correction=correction,
        created_at=attempt.created_at,
    )


async def report(
    session: AsyncSession,
    user_id: uuid.UUID,
    exercise_id: int,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime | None = None,
) -> bool:
    """The learner says the item is wrong: its answers stop counting; commits.

    The item is marked `reported`, the evidence of its answers is deleted and mastery
    replayed without it. Reporting again changes nothing. Returns whether this finished
    the set (the last unanswered item was the reported one).
    """
    now = now or datetime.now(UTC)
    item = await _item(session, user_id, exercise_id, lock=True)
    if item.status == "reported":
        return False
    item.status = "reported"
    removed: Iterable[str] = await session.scalars(
        delete(KCEvidence)
        .where(
            KCEvidence.user_id == user_id,
            KCEvidence.attempt_id.in_(select(Attempt.id).where(Attempt.exercise_id == exercise_id)),
        )
        .returning(KCEvidence.kc_id)
    )
    affected = set(removed)
    exercise_set = await session.get(ExerciseSet, item.set_id)
    assert exercise_set is not None  # FK
    set_done = False
    if exercise_set.status in OPEN_SET:
        _start(exercise_set, now)
        await session.flush()
        set_done = await _finish_if_done(session, exercise_set, now)
    await session.flush()
    await refresh(session, user_id, affected, rules=rules, catalog=catalog)
    await session.commit()
    return set_done
