"""user_cards / review_logs / user_word_book constraints (ADR 0011)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReviewLog, User, UserCard, UserWordBook, Word


async def _user_and_word(session: AsyncSession) -> tuple[User, Word]:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    word = Word(word=f"w{uuid.uuid4().hex[:8]}", translation="n. 词")
    session.add_all([user, word])
    await session.flush()
    return user, word


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"source": "import"}, "ck_user_cards_source"),
        ({"status": "forgotten"}, "ck_user_cards_status"),
        ({"state": 0}, "ck_user_cards_state"),
        ({"status": "learning", "due": None}, "ck_user_cards_learning_due"),
    ],
)
async def test_card_checks(
    db_session: AsyncSession, override: dict[str, object], constraint: str
) -> None:
    user, word = await _user_and_word(db_session)
    fields: dict[str, object] = {
        "user_id": user.id,
        "word_id": word.id,
        "source": "book",
        "status": "new",
    }
    db_session.add(UserCard(**(fields | override)))
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_one_card_per_word_and_deleting_the_user_removes_everything(
    db_session: AsyncSession,
) -> None:
    user, word = await _user_and_word(db_session)
    now = datetime.now(UTC)
    card = UserCard(
        user_id=user.id, word_id=word.id, source="book", status="learning", state=1, due=now
    )
    db_session.add_all([card, UserWordBook(user_id=user.id, book_id="cet4")])
    await db_session.flush()
    db_session.add(
        ReviewLog(
            card_id=card.id,
            user_id=user.id,
            rating=3,
            reviewed_at=now,
            card_before={},
            card_after={},
        )
    )
    await db_session.commit()
    user_id, word_id = user.id, word.id  # attributes expire on rollback

    db_session.add(UserCard(user_id=user_id, word_id=word_id, source="manual", status="new"))
    with pytest.raises(IntegrityError, match="uq_user_cards_user_id_word_id"):
        await db_session.flush()
    await db_session.rollback()

    await db_session.execute(delete(User).where(User.id == user_id))
    await db_session.commit()
    for model in (UserCard, ReviewLog, UserWordBook):
        assert (await db_session.scalars(select(model))).all() == []
    assert await db_session.get(Word, word_id) is not None  # global data stays
