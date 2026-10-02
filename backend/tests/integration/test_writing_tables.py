"""`writing_submissions` and writing evidence (task 38.1, Q38e)."""

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KCEvidence, User, WritingSubmission

KC = "g.past_simple_irregular"


async def _submission(session: AsyncSession) -> tuple[User, WritingSubmission]:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    submission = WritingSubmission(
        user_id=user.id, text="Last summer I go to Qingdao.", word_count=6, status="pending"
    )
    session.add(submission)
    await session.flush()
    return user, submission


def mistake(user: User, writing_id: int | None) -> KCEvidence:
    return KCEvidence(
        user_id=user.id,
        kc_id=KC,
        correct=False,
        evidence="production",
        source="writing",
        error_type="wrong_form",
        severity="medium",
        original="go",
        correction="went",
        writing_id=writing_id,
    )


async def test_deleting_a_submission_deletes_its_evidence(db_session: AsyncSession) -> None:
    user, submission = await _submission(db_session)
    db_session.add(mistake(user, submission.id))
    await db_session.flush()

    await db_session.execute(delete(WritingSubmission).where(WritingSubmission.id == submission.id))
    assert (await db_session.scalars(select(KCEvidence))).all() == []


async def test_writing_evidence_needs_its_submission(db_session: AsyncSession) -> None:
    user, _ = await _submission(db_session)
    db_session.add(mistake(user, None))
    with pytest.raises(IntegrityError, match="writing_source"):
        await db_session.flush()


async def test_only_writing_evidence_points_at_a_submission(db_session: AsyncSession) -> None:
    user, submission = await _submission(db_session)
    row = mistake(user, submission.id)
    row.source = "chat"
    db_session.add(row)
    with pytest.raises(IntegrityError, match="writing_source"):
        await db_session.flush()


async def test_deleting_the_user_deletes_submissions(db_session: AsyncSession) -> None:
    user, _ = await _submission(db_session)
    await db_session.execute(delete(User).where(User.id == user.id))
    assert (await db_session.scalars(select(WritingSubmission))).all() == []


async def test_status_is_checked(db_session: AsyncSession) -> None:
    _, submission = await _submission(db_session)
    submission.status = "reviewing"
    with pytest.raises(IntegrityError, match="status"):
        await db_session.flush()
