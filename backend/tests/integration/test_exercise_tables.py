import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise.formats import Choice4, parse_body
from app.db.models import Attempt, Exercise, ExerciseSet, KCEvidence, KCMastery, User

KC = "g.past_simple_regular"
BODY = Choice4.model_validate(
    {
        "content": {"stem": "I ___ him yesterday.", "options": ["saw", "see", "seen", "sees"]},
        "answer": {"correct": "saw", "explanation": "A finished time takes the past simple."},
    }
)


async def _user(session: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    return user


async def _answered(session: AsyncSession, user: User) -> tuple[ExerciseSet, Exercise, Attempt]:
    exercise_set = ExerciseSet(
        user_id=user.id,
        origin="dashboard",
        status="in_progress",
        kc_plan=[{"kc_id": KC, "format": "choice4", "difficulty": -0.5}],
    )
    session.add(exercise_set)
    await session.flush()
    exercise = Exercise(
        user_id=user.id,
        set_id=exercise_set.id,
        position=0,
        kc_id=KC,
        format=BODY.format,
        content=BODY.content.model_dump(),
        answer=BODY.answer.model_dump(),
        difficulty=-0.5,
        status="ok",
    )
    session.add(exercise)
    await session.flush()
    attempt = Attempt(
        user_id=user.id, exercise_id=exercise.id, response={"choice": "saw"}, correct=True
    )
    session.add(attempt)
    await session.flush()
    return exercise_set, exercise, attempt


def evidence(user: User, **kw: object) -> KCEvidence:
    fields: dict[str, object] = {
        "user_id": user.id,
        "kc_id": KC,
        "correct": True,
        "evidence": "recognition",
        "source": "exercise",
        "format": "choice4",
    }
    return KCEvidence(**(fields | kw))


async def test_item_round_trips_through_jsonb(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    _, exercise, _ = await _answered(db_session, user)
    await db_session.commit()
    db_session.expunge_all()
    stored = await db_session.get(Exercise, exercise.id)
    assert stored is not None
    assert parse_body(stored.format, stored.content, stored.answer) == BODY


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"format": None}, "ck_kc_evidence_format_source"),  # practice without format
        ({"source": "chat"}, "ck_kc_evidence_format_source"),  # format outside practice
        ({"format": "essay"}, "ck_kc_evidence_format"),
        ({"source": "email", "format": None}, "ck_kc_evidence_source"),
    ],
)
async def test_evidence_format_checks(
    db_session: AsyncSession, override: dict[str, object], constraint: str
) -> None:
    user = await _user(db_session)
    db_session.add(evidence(user, **override))
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


@pytest.mark.parametrize("source", ["writing", "reading"])
async def test_new_sources_without_format(db_session: AsyncSession, source: str) -> None:
    user = await _user(db_session)
    db_session.add(evidence(user, source=source, format=None))
    await db_session.flush()


@pytest.mark.parametrize(
    ("model", "fields", "constraint"),
    [
        (ExerciseSet, {"origin": "email"}, "ck_exercise_sets_origin"),
        (ExerciseSet, {"status": "paused"}, "ck_exercise_sets_status"),
        (Exercise, {"format": "essay"}, "ck_exercises_format"),
        (Exercise, {"status": "hidden"}, "ck_exercises_status"),
    ],
)
async def test_exercise_checks(
    db_session: AsyncSession, model: type, fields: dict[str, object], constraint: str
) -> None:
    user = await _user(db_session)
    exercise_set, exercise, _ = await _answered(db_session, user)
    row = exercise_set if model is ExerciseSet else exercise
    for name, value in fields.items():
        setattr(row, name, value)
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"state": 4}, "ck_kc_mastery_state"),
        ({"mastered_at": datetime.now(UTC)}, "ck_kc_mastery_mastered_due"),  # learned, no due
        ({"due": datetime.now(UTC)}, "ck_kc_mastery_mastered_due"),  # due, never learned
    ],
)
async def test_mastery_fsrs_checks(
    db_session: AsyncSession, fields: dict[str, object], constraint: str
) -> None:
    user = await _user(db_session)
    db_session.add(
        KCMastery(
            user_id=user.id, kc_id=KC, kind="grammar", p_mastery=0.5, rules_version="v", **fields
        )
    )
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_mastery_progress_defaults(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    db_session.add(
        KCMastery(user_id=user.id, kc_id=KC, kind="grammar", p_mastery=0.5, rules_version="v")
    )
    await db_session.commit()
    db_session.expunge_all()
    row = await db_session.scalar(select(KCMastery))
    assert row is not None
    assert row.formats_passed == [] and row.correct_span_hours == 0.0
    assert row.mastered_at is None and row.due is None


async def test_evidence_outlives_its_set_and_dies_with_user(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    exercise_set, _, attempt = await _answered(db_session, user)
    db_session.add(evidence(user, attempt_id=attempt.id))
    await db_session.commit()

    # Deleting a set takes its items and answers; the evidence stays (ADR 0012).
    await db_session.delete(exercise_set)
    await db_session.commit()
    db_session.expunge_all()
    assert await db_session.scalar(select(Exercise)) is None
    assert await db_session.scalar(select(Attempt)) is None
    row = await db_session.scalar(select(KCEvidence))
    assert row is not None and row.attempt_id is None

    await _answered(db_session, user)
    await db_session.commit()
    await db_session.delete(await db_session.get(User, user.id))
    await db_session.commit()
    for model in (ExerciseSet, Exercise, Attempt, KCEvidence):
        assert await db_session.scalar(select(model)) is None
