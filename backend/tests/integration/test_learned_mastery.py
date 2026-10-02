"""Practice evidence → "learned" progress and grammar FSRS in kc_mastery (ADR 0021 §7)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.exercise.formats import SPECS, Format
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.db.models import Attempt, Exercise, ExerciseSet, KCEvidence, KCMastery, User, UserProfile

KC = "g.present_simple_third_person"  # A1; a B1 learner starts at p = 0.9
CATALOG, RULES = get_grammar_catalog(), get_rules()
T0 = datetime(2026, 10, 1, 9, tzinfo=UTC)


async def learner(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    session.add(UserProfile(user_id=user.id, cefr_level="B1"))
    await session.flush()
    return user.id


async def practice_set(
    session: AsyncSession, user_id: uuid.UUID, answers: list[tuple[Format, float, bool]]
) -> None:
    """One set: each answer is (format, hours after T0, correct), stored as task 34 will."""
    exercise_set = ExerciseSet(user_id=user_id, origin="learner", status="done", kc_plan=[])
    session.add(exercise_set)
    await session.flush()
    for position, (fmt, hours, correct) in enumerate(answers):
        exercise = Exercise(
            user_id=user_id,
            set_id=exercise_set.id,
            position=position,
            kc_id=KC,
            format=fmt,
            content={},
            answer={},
            difficulty=0.0,
            status="ok",
        )
        session.add(exercise)
        await session.flush()
        attempt = Attempt(user_id=user_id, exercise_id=exercise.id, response={}, correct=correct)
        session.add(attempt)
        await session.flush()
        for kind in SPECS[fmt].evidence:
            session.add(
                KCEvidence(
                    user_id=user_id,
                    kc_id=KC,
                    correct=correct,
                    evidence=kind,
                    source="exercise",
                    format=fmt,
                    attempt_id=attempt.id,
                    error_type=None if correct else "wrong_choice",
                    severity=None if correct else "medium",
                    created_at=T0 + timedelta(hours=hours),
                )
            )
    await session.flush()


async def row(session: AsyncSession, user_id: uuid.UUID) -> KCMastery:
    await mastery.refresh(session, user_id, [KC], rules=RULES, catalog=CATALOG)
    await session.commit()
    session.expunge_all()
    found = await session.scalar(select(KCMastery).where(KCMastery.user_id == user_id))
    assert found is not None
    return found


async def test_practice_over_two_days_makes_a_kc_learned(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    await practice_set(db_session, user_id, [("choice4", 0, True), ("cloze", 0.1, True)])
    first = await row(db_session, user_id)
    assert first.formats_passed == ["choice4", "cloze"]
    assert first.mastered_at is None and first.due is None

    await practice_set(db_session, user_id, [("transform", 21, True), ("find_fix", 21.1, True)])
    learned = await row(db_session, user_id)
    assert learned.formats_passed == ["choice4", "cloze", "find_fix", "transform"]
    assert learned.correct_span_hours == 21.1
    assert learned.mastered_at == T0 + timedelta(hours=21)
    assert learned.state == 2  # review
    assert learned.due is not None and learned.due > T0 + timedelta(days=3)


async def test_a_wrong_answer_in_a_later_set_brings_the_kc_due(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    await practice_set(db_session, user_id, [("choice4", 0, True), ("cloze", 0.1, True)])
    await practice_set(db_session, user_id, [("transform", 21, True)])
    before = await row(db_session, user_id)
    await practice_set(db_session, user_id, [("choice4", 100, True), ("cloze", 100.1, False)])
    after = await row(db_session, user_id)
    assert after.mastered_at == before.mastered_at
    assert after.state == 3  # relearning
    assert after.last_review == T0 + timedelta(hours=100.1)
    assert before.due is not None and after.due is not None and after.due < before.due


async def test_stale_rows_are_rebuilt_with_learned_columns(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    await practice_set(db_session, user_id, [("choice4", 0, True), ("cloze", 0.1, True)])
    await practice_set(db_session, user_id, [("transform", 21, True)])
    current = await row(db_session, user_id)
    expected = (current.formats_passed, current.mastered_at, current.due)
    await db_session.execute(
        update(KCMastery)
        .where(KCMastery.user_id == user_id)
        .values(rules_version="old", formats_passed=[], mastered_at=None, due=None, state=None)
    )
    assert await mastery.ensure_current(db_session, user_id, rules=RULES, catalog=CATALOG)
    await db_session.commit()
    db_session.expunge_all()
    rebuilt = await db_session.scalar(select(KCMastery).where(KCMastery.user_id == user_id))
    assert rebuilt is not None
    assert (rebuilt.formats_passed, rebuilt.mastered_at, rebuilt.due) == expected
    assert rebuilt.mastered_at is not None
