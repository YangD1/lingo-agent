"""A set the learner answers while its other items are still being written (ADR 0048
§2-§3): items are stored as they pass the critic, and the end of the set is stored
around the answers."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise import service
from app.adaptive.exercise.answer import NotAnswerableError
from app.adaptive.exercise.formats import ChoiceResponse, parse_body
from app.agents.exercise_graph import MadeItem, SetResult
from app.db.models import Exercise, ExerciseSet
from tests.integration.test_exercise_answer import CATALOG, ITEMS, KC, OTHER, learner, submit


def made(position: int, kc_id: str = KC, bank: bool = False) -> MadeItem:
    content, key = ITEMS["choice4"]
    return MadeItem(
        position=position,
        kc_id=kc_id,
        format="choice4",
        body=parse_body("choice4", content, key),
        difficulty=0.0,
        ratings={},
        critic=None if bank else {"verdict": "pass"},
        model=None if bank else "fake:writer",
        bank_item_id="bank-1" if bank else None,
    )


async def writing(session: AsyncSession, user_id: uuid.UUID, kcs: list[str]) -> uuid.UUID:
    row = ExerciseSet(
        user_id=user_id,
        origin="quiz",
        status="generating",
        kc_plan=[{"kc_id": kc, "format": "choice4", "difficulty": 0.0} for kc in kcs],
    )
    session.add(row)
    await session.commit()
    return row.id


async def publish(
    session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID, item: MadeItem
) -> int:
    assert await service.publish_item(session, user_id, set_id, item)
    await session.commit()
    stored = await session.scalar(
        select(Exercise.id).where(Exercise.set_id == set_id, Exercise.position == item.position)
    )
    assert stored is not None
    return stored


async def the_set(session: AsyncSession, set_id: uuid.UUID) -> ExerciseSet:
    session.expire_all()
    row = await session.get(ExerciseSet, set_id)
    assert row is not None
    return row


async def test_a_published_item_is_answered_before_the_set_is_written(
    db_session: AsyncSession,
) -> None:
    user_id = await learner(db_session)
    set_id = await writing(db_session, user_id, [KC, OTHER])
    first = await publish(db_session, user_id, set_id, made(0))

    answered = await submit(db_session, user_id, first, ChoiceResponse(choice="lives"))

    assert answered.correct and not answered.set_done
    row = await the_set(db_session, set_id)
    assert row.status == "generating" and row.started_at is not None
    # The planned KC with no item yet is kept as it was before too.
    assert row.mastery_before == {
        KC: {"p_mastery": None, "learned": False},
        OTHER: {"p_mastery": None, "learned": False},
    }


async def test_the_rest_of_the_set_is_stored_once_and_the_set_goes_on(
    db_session: AsyncSession,
) -> None:
    user_id = await learner(db_session)
    set_id = await writing(db_session, user_id, [KC, OTHER, KC])
    first = await publish(db_session, user_id, set_id, made(0))
    await publish(db_session, user_id, set_id, made(1, OTHER))
    await submit(db_session, user_id, first, ChoiceResponse(choice="lives"))
    wider = next(kc.id for kc in CATALOG.kcs if kc.id not in (KC, OTHER))

    saved = await service.save_result(
        db_session,
        user_id,
        set_id,
        SetResult([made(0), made(1, OTHER), made(2, wider, bank=True)], [], None, 1),
    )
    await db_session.commit()

    assert saved == service.Saved(stored=True, done=False)
    row = await the_set(db_session, set_id)
    assert row.status == "in_progress"
    assert row.mastery_before is not None and set(row.mastery_before) == {KC, OTHER, wider}
    positions = await db_session.scalars(
        select(Exercise.position).where(Exercise.set_id == set_id).order_by(Exercise.position)
    )
    assert list(positions) == [0, 1, 2]


async def test_a_set_answered_through_while_written_is_done_once_stored(
    db_session: AsyncSession,
) -> None:
    user_id = await learner(db_session)
    set_id = await writing(db_session, user_id, [KC, KC])
    first = await publish(db_session, user_id, set_id, made(0))
    await submit(db_session, user_id, first, ChoiceResponse(choice="lives"))

    # Slot 1 was dropped: nothing the learner has not answered is left.
    saved = await service.save_result(db_session, user_id, set_id, SetResult([made(0)], [], None))
    await db_session.commit()

    assert saved == service.Saved(stored=True, done=True)
    row = await the_set(db_session, set_id)
    assert row.status == "done" and row.finished_at is not None


async def test_a_started_set_is_not_failed_for_being_short(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    set_id = await writing(db_session, user_id, [KC, KC, KC])
    first = await publish(db_session, user_id, set_id, made(0))
    await publish(db_session, user_id, set_id, made(1))
    await submit(db_session, user_id, first, ChoiceResponse(choice="lives"))

    saved = await service.save_result(
        db_session, user_id, set_id, SetResult([made(0), made(1)], [], "generation_failed")
    )
    await db_session.commit()

    assert saved == service.Saved(stored=True, done=False)
    row = await the_set(db_session, set_id)
    assert (row.status, row.error_code) == ("in_progress", None)


async def test_nothing_is_published_into_a_set_given_up_on(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    set_id = await writing(db_session, user_id, [KC])
    row = await the_set(db_session, set_id)
    row.status = "failed"
    await db_session.commit()

    assert not await service.publish_item(db_session, user_id, set_id, made(0))


async def test_a_failed_set_cannot_be_answered(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    set_id = await writing(db_session, user_id, [KC, KC])
    first = await publish(db_session, user_id, set_id, made(0))
    row = await the_set(db_session, set_id)
    row.status = "failed"
    await db_session.commit()

    with pytest.raises(NotAnswerableError):
        await submit(db_session, user_id, first, ChoiceResponse(choice="lives"))
