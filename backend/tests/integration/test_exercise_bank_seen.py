"""Which bank items a learner has seen, and the calibrated bank (ADR 0021 §3, Q33c)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise import bank
from app.adaptive.placement.items import get_item_bank
from app.adaptive.rules import get_rules
from app.db.models import Exercise, ExerciseSet, PlacementItemStat, PlacementSession, User

RULES = get_rules()
T0 = datetime(2026, 9, 1, tzinfo=UTC)


async def learner(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    return user.id


def placement_test(
    user_id: uuid.UUID, at: datetime, items: list[str], status: str = "done"
) -> PlacementSession:
    row = PlacementSession(
        user_id=user_id, status=status, stage="grammar", seed=1, rules_version=RULES.version
    )
    if status == "done":
        grammar = [{"item_id": i, "correct": True} for i in items]
        row.result = {"answers": {"vocab": [], "grammar": grammar}}
        row.finished_at = at
    return row


async def test_seen_items_come_from_tests_and_practice(db_session: AsyncSession) -> None:
    user_id = await learner(db_session)
    other = await learner(db_session)
    db_session.add_all(
        [
            placement_test(user_id, T0, ["p.a.1", "p.b.1"]),
            placement_test(user_id, T0 + timedelta(days=5), ["p.a.1"]),
            placement_test(user_id, T0, ["p.z.1"], status="abandoned"),
            placement_test(other, T0, ["p.c.1"]),
        ]
    )
    exercise_set = ExerciseSet(user_id=user_id, origin="learner", status="done", kc_plan=[])
    db_session.add(exercise_set)
    await db_session.flush()
    for position, (item_id, status, days) in enumerate(
        [("p.b.1", "ok", 10), ("p.d.1", "rejected", 10), ("p.e.1", "reported", 2)]
    ):
        db_session.add(
            Exercise(
                user_id=user_id,
                set_id=exercise_set.id,
                position=position,
                kc_id="g.x",
                format="choice4",
                content={},
                answer={},
                difficulty=0.0,
                status=status,
                bank_item_id=item_id,
                created_at=T0 + timedelta(days=days),
            )
        )
    await db_session.flush()

    seen = await bank.seen_items(db_session, user_id)

    assert seen == {
        "p.a.1": T0 + timedelta(days=5),
        "p.b.1": T0 + timedelta(days=10),
        "p.e.1": T0 + timedelta(days=2),
    }


async def test_bank_uses_difficulties_calibrated_on_enough_answers(
    db_session: AsyncSession,
) -> None:
    first, second = get_item_bank().items[:2]
    need = RULES.placement.grammar.calibrated_min_attempts
    db_session.add_all(
        [
            PlacementItemStat(item_id=first.id, difficulty=first.difficulty + 1, attempts=need),
            PlacementItemStat(item_id=second.id, difficulty=9.0, attempts=need - 1),
        ]
    )
    await db_session.flush()

    loaded = await bank.load_bank(db_session, RULES)

    assert loaded.get(first.id).difficulty == first.difficulty + 1  # type: ignore[union-attr]
    assert loaded.get(second.id).difficulty == second.difficulty  # type: ignore[union-attr]
