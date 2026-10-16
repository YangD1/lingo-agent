"""Practice sets in the database (ADR 0021 §3-§4)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise import answer as answering_
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


async def publish_item(
    session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID, item: MadeItem
) -> bool:
    """Store an item the critic passed while the rest of the set is still being written
    (ADR 0048 §2): the learner can answer it at once. Only into a set still
    `generating`; returns whether it was stored. Does not commit."""
    status = await session.scalar(
        select(ExerciseSet.status).where(ExerciseSet.id == set_id).with_for_update()
    )
    if status != "generating":
        return False
    session.add(_row(user_id, set_id, item, "ok"))
    await session.flush()
    return True


@dataclass(frozen=True, slots=True)
class Saved:
    stored: bool
    # Every item was answered while the set was being written: it is done now.
    done: bool = False


async def save_result(
    session: AsyncSession,
    user_id: uuid.UUID,
    set_id: uuid.UUID,
    result: SetResult,
    *,
    now: datetime | None = None,
) -> Saved:
    """Store a generated set: the items not published yet, the critic's rejects, and
    its status (ADR 0048 §2-§3).

    Only a set still `generating` takes a result, so a result arriving after the set
    was given up on (`failed` by the service) is dropped. A set the learner already
    answered in is never failed for having too few items; it goes on as `in_progress`,
    or is `done` when every item has an answer. Does not commit.
    """
    now = now or datetime.now(UTC)
    exercise_set = await session.scalar(
        select(ExerciseSet).where(ExerciseSet.id == set_id).with_for_update()
    )
    if exercise_set is None or exercise_set.status != "generating":
        return Saved(stored=False)
    published = set(
        await session.scalars(
            select(Exercise.position).where(
                Exercise.set_id == set_id, Exercise.status != "rejected"
            )
        )
    )
    answering = exercise_set.mastery_before is not None
    ready = result.error_code is None or (answering and bool(published or result.items))
    session.add_all(_row(user_id, set_id, item, "rejected") for item in result.rejected)
    if ready:
        session.add_all(
            _row(user_id, set_id, item, "ok")
            for item in result.items
            if item.position not in published
        )
    await session.flush()
    if not ready:
        exercise_set.status, exercise_set.error_code = "failed", result.error_code
        return Saved(stored=True)
    if not answering:
        exercise_set.status = "ready"
        return Saved(stored=True)
    exercise_set.status = "in_progress"
    await answering_.record_mastery_before(session, exercise_set)
    return Saved(stored=True, done=await answering_.finish_if_done(session, exercise_set, now))


@dataclass(frozen=True, slots=True)
class HowMade:
    """How a set's items came about, for the learner to see (ADR 0013 §3): counts and
    model names only, never the rejected items or the critic's reasons."""

    written: int
    from_bank: int
    # Drafts the critic turned down before the learner saw the set.
    rejected: int
    writers: tuple[str, ...]
    reviewers: tuple[str, ...]


async def how_made(session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID) -> HowMade:
    rows = (
        await session.execute(
            select(Exercise.status, Exercise.bank_item_id, Exercise.model, Exercise.critic).where(
                Exercise.user_id == user_id, Exercise.set_id == set_id
            )
        )
    ).all()
    shown = [r for r in rows if r.status != "rejected"]
    return HowMade(
        written=sum(1 for r in shown if r.bank_item_id is None),
        from_bank=sum(1 for r in shown if r.bank_item_id is not None),
        rejected=sum(1 for r in rows if r.status == "rejected"),
        writers=tuple(sorted({r.model for r in shown if r.model})),
        reviewers=tuple(
            sorted({r.critic["model"] for r in shown if r.critic and r.critic.get("model")})
        ),
    )
