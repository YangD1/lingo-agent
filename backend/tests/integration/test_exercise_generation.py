"""A practice set generated with fake models and stored (ADR 0021 §3)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise import service
from app.adaptive.exercise.formats import parse_body
from app.agents.exercise_graph import SetResult
from app.db.models import Exercise, ExerciseSet, User
from tests.unit.test_exercise_graph import RULES, FakeModels, run


async def new_set(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    row = ExerciseSet(user_id=user.id, origin="learner", status="generating", kc_plan=[])
    session.add(row)
    await session.flush()
    return user.id, row.id


async def items(session: AsyncSession, set_id: uuid.UUID) -> list[Exercise]:
    query = select(Exercise).where(Exercise.set_id == set_id)
    return list(await session.scalars(query.order_by(Exercise.position, Exercise.id)))


async def test_items_and_rejects_are_stored_and_read_back(db_session: AsyncSession) -> None:
    user_id, set_id = await new_set(db_session)
    rounds = 1 + RULES.practice.max_regenerations
    result, _ = await run(FakeModels(bad={(0, 2)} | {(r, 4) for r in range(rounds)}))

    assert await service.save_result(db_session, user_id, set_id, result)

    exercise_set = await db_session.get(ExerciseSet, set_id)
    assert exercise_set is not None and exercise_set.status == "ready"
    rows = await items(db_session, set_id)
    ok = [r for r in rows if r.status == "ok"]
    assert [r.position for r in ok] == list(range(6))
    assert sum(r.status == "rejected" for r in rows) == 1 + rounds
    for row in rows:  # the stored JSON is a valid item of its format
        parse_body(row.format, row.content, row.answer)
    bank_item = ok[4]
    assert bank_item.bank_item_id is not None and bank_item.critic is None
    assert bank_item.model is None
    written = ok[0]
    assert written.model == "fake:writer" and written.critic is not None
    assert written.critic["verdict"] == "pass" and written.ratings
    assert await service.how_made(db_session, user_id, set_id) == service.HowMade(
        written=5,
        from_bank=1,
        rejected=1 + rounds,
        writers=("fake:writer",),
        reviewers=("fake:critic",),
    )
    assert (await service.how_made(db_session, uuid.uuid4(), set_id)).written == 0


async def test_a_failed_set_keeps_its_error_and_no_items(db_session: AsyncSession) -> None:
    user_id, set_id = await new_set(db_session)

    stored = await service.save_result(
        db_session, user_id, set_id, SetResult([], [], "no_llm_configured")
    )

    assert stored
    exercise_set = await db_session.get(ExerciseSet, set_id)
    assert exercise_set is not None
    assert (exercise_set.status, exercise_set.error_code) == ("failed", "no_llm_configured")
    assert await items(db_session, set_id) == []


async def test_a_set_given_up_on_takes_no_result(db_session: AsyncSession) -> None:
    user_id, set_id = await new_set(db_session)
    exercise_set = await db_session.get(ExerciseSet, set_id)
    assert exercise_set is not None
    exercise_set.status = "failed"
    await db_session.flush()
    result, _ = await run(FakeModels())

    assert not await service.save_result(db_session, user_id, set_id, result)
    assert await items(db_session, set_id) == []
