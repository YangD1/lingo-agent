"""What the practice page reads (ADR 0021 §5, task 35).

A set as the learner sees it: items without their answers until answered, the result
of each first answer, how the items were made and, once the set is done, what changed
for its KCs. Rejected items never appear; an item's key is shown only after it was
answered (or reported), and `rewrite_own` leaves out the evidence id it was made from.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.adaptive.exercise.service import HowMade, how_made
from app.adaptive.kc.catalog import GrammarCatalog, GrammarKC
from app.adaptive.learner import MasteryState, mastery_state
from app.adaptive.rules import Rules
from app.db.models import Attempt, Exercise, ExerciseSet, KCMastery

# Never sent to the learner's page.
_PRIVATE_CONTENT = ("evidence_id",)


class SetNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class KCName:
    id: str
    name_en: str
    name_zh: str
    cefr: str


@dataclass(frozen=True, slots=True)
class Result:
    correct: bool
    response: dict[str, Any]
    # explanation, corrected, other_mistakes (each with the KC's names), model.
    feedback: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    position: int
    kc: KCName
    format: str
    content: dict[str, Any]
    # ok, or reported by the learner.
    status: str
    from_bank: bool
    # The key, once answered or reported.
    answer: dict[str, Any] | None
    result: Result | None


@dataclass(frozen=True, slots=True)
class Mastery:
    # None: no evidence for the KC at that time.
    p_mastery: float | None
    state: MasteryState | None
    learned: bool


@dataclass(frozen=True, slots=True)
class Progress:
    """Where the KC stands on the way to "learned" (rules.yaml mastery_gate)."""

    formats_passed: list[str]
    correct_span_hours: float
    last_mistake_at: datetime | None
    mastered_at: datetime | None
    due: datetime | None


@dataclass(frozen=True, slots=True)
class KCChange:
    kc: KCName
    items: int
    correct: int
    before: Mastery
    after: Mastery
    progress: Progress | None


@dataclass(frozen=True, slots=True)
class Summary:
    total: int
    correct: int
    kcs: list[KCChange]


@dataclass(frozen=True, slots=True)
class SetView:
    id: uuid.UUID
    status: str
    origin: str
    focus_kc: KCName | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    items: list[Item]
    how_made: HowMade | None
    summary: Summary | None


@dataclass(frozen=True, slots=True)
class SetBrief:
    id: uuid.UUID
    status: str
    origin: str
    focus_kc: KCName | None
    created_at: datetime
    finished_at: datetime | None
    total: int
    answered: int
    correct: int


def kc_name(kc_id: str, catalog: GrammarCatalog) -> KCName:
    kc: GrammarKC | None = catalog.get(kc_id)
    if kc is None:  # a KC dropped from the catalog since: show its id
        return KCName(kc_id, kc_id, kc_id, "")
    return KCName(kc.id, kc.name_en, kc.name_zh, kc.cefr)


def _feedback(feedback: dict[str, Any], catalog: GrammarCatalog) -> dict[str, Any]:
    others = [{**m, "kc": kc_name(m["kc_id"], catalog)} for m in feedback.get("other_mistakes", [])]
    return {**feedback, "other_mistakes": others}


async def _own_set(session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID) -> ExerciseSet:
    row = await session.get(ExerciseSet, set_id)
    if row is None or row.user_id != user_id:
        raise SetNotFoundError(set_id)
    return row


async def set_of_item(session: AsyncSession, user_id: uuid.UUID, exercise_id: int) -> uuid.UUID:
    set_id = await session.scalar(
        select(Exercise.set_id).where(Exercise.id == exercise_id, Exercise.user_id == user_id)
    )
    if set_id is None:
        raise SetNotFoundError(exercise_id)
    return set_id


async def _items(
    session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID, catalog: GrammarCatalog
) -> list[Item]:
    first = (
        select(Attempt)
        .where(Attempt.user_id == user_id)
        .ext(distinct_on(Attempt.exercise_id))
        .order_by(Attempt.exercise_id, Attempt.id)
        .subquery()
    )
    attempt = aliased(Attempt, first)
    rows = await session.execute(
        select(Exercise, attempt)
        .outerjoin(attempt, attempt.exercise_id == Exercise.id)
        .where(
            Exercise.user_id == user_id,
            Exercise.set_id == set_id,
            Exercise.status != "rejected",
        )
        .order_by(Exercise.position)
    )
    out: list[Item] = []
    for item, answered in rows.all():
        result = (
            Result(
                answered.correct,
                answered.response,
                _feedback(answered.feedback, catalog),
                answered.created_at,
            )
            if answered is not None
            else None
        )
        shown = result is not None or item.status == "reported"
        out.append(
            Item(
                id=item.id,
                position=item.position,
                kc=kc_name(item.kc_id, catalog),
                format=item.format,
                content={k: v for k, v in item.content.items() if k not in _PRIVATE_CONTENT},
                status=item.status,
                from_bank=item.bank_item_id is not None,
                answer=item.answer if shown else None,
                result=result,
            )
        )
    return out


def _mastery(row: KCMastery | None, rules: Rules) -> Mastery:
    if row is None:
        return Mastery(None, None, False)
    return Mastery(row.p_mastery, mastery_state(row.p_mastery, rules), row.mastered_at is not None)


def _before(snapshot: dict[str, Any] | None, kc_id: str, rules: Rules) -> Mastery:
    entry = (snapshot or {}).get(kc_id)
    if not entry or entry.get("p_mastery") is None:
        return Mastery(None, None, False)
    p = float(entry["p_mastery"])
    return Mastery(p, mastery_state(p, rules), bool(entry.get("learned")))


async def _summary(
    session: AsyncSession,
    exercise_set: ExerciseSet,
    items: list[Item],
    rules: Rules,
    catalog: GrammarCatalog,
) -> Summary:
    """Per KC of the set: its items, how many were right, and mastery before and now.
    Reported items count for nothing."""
    counted = [i for i in items if i.status == "ok" and i.result is not None]
    kc_ids = list(dict.fromkeys(i.kc.id for i in items))
    rows = {
        row.kc_id: row
        for row in await session.scalars(
            select(KCMastery).where(
                KCMastery.user_id == exercise_set.user_id, KCMastery.kc_id.in_(kc_ids)
            )
        )
    }
    changes = []
    for kc_id in kc_ids:
        mine = [i for i in counted if i.kc.id == kc_id]
        row = rows.get(kc_id)
        progress = (
            Progress(
                list(row.formats_passed),
                row.correct_span_hours,
                row.last_mistake_at,
                row.mastered_at,
                row.due,
            )
            if row is not None
            else None
        )
        changes.append(
            KCChange(
                kc=kc_name(kc_id, catalog),
                items=len(mine),
                correct=sum(1 for i in mine if i.result and i.result.correct),
                before=_before(exercise_set.mastery_before, kc_id, rules),
                after=_mastery(row, rules),
                progress=progress,
            )
        )
    return Summary(
        total=len(counted),
        correct=sum(1 for i in counted if i.result and i.result.correct),
        kcs=changes,
    )


async def get_set(
    session: AsyncSession,
    user_id: uuid.UUID,
    set_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
) -> SetView:
    exercise_set = await _own_set(session, user_id, set_id)
    items = await _items(session, user_id, set_id, catalog)
    shown = exercise_set.status in ("ready", "in_progress", "done")
    return SetView(
        id=exercise_set.id,
        status=exercise_set.status,
        origin=exercise_set.origin,
        focus_kc=kc_name(exercise_set.focus_kc_id, catalog) if exercise_set.focus_kc_id else None,
        error_code=exercise_set.error_code,
        created_at=exercise_set.created_at,
        started_at=exercise_set.started_at,
        finished_at=exercise_set.finished_at,
        items=items,
        how_made=await how_made(session, user_id, set_id) if shown else None,
        summary=(
            await _summary(session, exercise_set, items, rules, catalog)
            if exercise_set.status == "done"
            else None
        ),
    )


async def recent_sets(
    session: AsyncSession, user_id: uuid.UUID, *, catalog: GrammarCatalog, limit: int
) -> list[SetBrief]:
    """The learner's latest sets they started, newest first, with answer counts."""
    first = (
        select(Attempt.exercise_id, Attempt.correct)
        .where(Attempt.user_id == user_id)
        .ext(distinct_on(Attempt.exercise_id))
        .order_by(Attempt.exercise_id, Attempt.id)
        .subquery()
    )
    counts = (
        select(
            Exercise.set_id,
            func.count().label("total"),
            func.count(first.c.exercise_id).label("answered"),
            func.count().filter(first.c.correct.is_(True)).label("correct"),
        )
        .outerjoin(first, first.c.exercise_id == Exercise.id)
        .where(Exercise.user_id == user_id, Exercise.status == "ok")
        .group_by(Exercise.set_id)
        .subquery()
    )
    rows = await session.execute(
        select(ExerciseSet, counts.c.total, counts.c.answered, counts.c.correct)
        .outerjoin(counts, counts.c.set_id == ExerciseSet.id)
        .where(ExerciseSet.user_id == user_id, ExerciseSet.started_at.is_not(None))
        .order_by(ExerciseSet.created_at.desc())
        .limit(limit)
    )
    return [
        SetBrief(
            id=s.id,
            status=s.status,
            origin=s.origin,
            focus_kc=kc_name(s.focus_kc_id, catalog) if s.focus_kc_id else None,
            created_at=s.created_at,
            finished_at=s.finished_at,
            total=total or 0,
            answered=answered or 0,
            correct=correct or 0,
        )
        for s, total, answered, correct in rows.all()
    ]
