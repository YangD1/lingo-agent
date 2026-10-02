"""Practice sets in the database (ADR 0021 §3-§4)."""

import uuid
from typing import Any

from sqlalchemy import CursorResult, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.exercise_graph import MadeItem, SetResult
from app.db.models import Exercise, ExerciseSet


def _row(user_id: uuid.UUID, set_id: uuid.UUID, item: MadeItem, status: str) -> Exercise:
    return Exercise(
        user_id=user_id,
        set_id=set_id,
        position=item.position,
        kc_id=item.kc_id,
        format=item.format,
        content=item.body.content.model_dump(mode="json"),
        answer=item.body.answer.model_dump(mode="json"),
        difficulty=item.difficulty,
        ratings=dict(item.ratings),
        critic=dict(item.critic) if item.critic is not None else None,
        status=status,
        bank_item_id=item.bank_item_id,
        model=item.model,
    )


async def save_result(
    session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID, result: SetResult
) -> bool:
    """Store a generated set: its items, the critic's rejects, and `ready` or `failed`.

    Only a set still `generating` takes a result, so a result arriving after the set
    was given up on (`failed` by the service) is dropped; returns whether it was stored.
    Does not commit.
    """
    ready = result.error_code is None
    claimed: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        update(ExerciseSet)
        .where(ExerciseSet.id == set_id, ExerciseSet.status == "generating")
        .values(status="ready" if ready else "failed", error_code=result.error_code)
    )
    if claimed.rowcount == 0:
        return False
    session.add_all(_row(user_id, set_id, item, "rejected") for item in result.rejected)
    if ready:
        session.add_all(_row(user_id, set_id, item, "ok") for item in result.items)
    await session.flush()
    return True
