"""When to remind a learner of the placement test (task 50, Q50a-c).

One reminder at a time, the strongest reason first: a test left halfway, never tested,
enough of the current level learned, or the last test getting old. `decide` is pure;
`load` reads what it needs. Each reminder carries a key: "Not now" silences that key
for `advice.reminder_snooze_days`, and a new reason (or a new test) gets a new key, so
it reminds again.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog
from app.adaptive.rules import Rules
from app.db.models import KCMastery, PlacementSession, ReminderDismissal

Reason = Literal["resume", "never", "progress", "age"]


@dataclass(frozen=True, slots=True)
class LastTest:
    id: uuid.UUID
    finished_at: datetime
    # The level that test gave (Q50g: the current level).
    level: CefrLevel
    # Grammar points at that level, and how many of them are learned now.
    learned: int
    total: int


@dataclass(frozen=True, slots=True)
class ReminderSignals:
    open_test: uuid.UUID | None
    last: LastTest | None


@dataclass(frozen=True, slots=True)
class Reminder:
    reason: Reason
    # What "Not now" silences.
    key: str
    # Whole days since the last finished test; None if never.
    days_since: int | None = None
    level: CefrLevel | None = None
    learned: int | None = None
    total: int | None = None
    # "Not now" on this key within `advice.reminder_snooze_days`: say nothing unasked.
    snoozed: bool = False


def decide(signals: ReminderSignals, rules: Rules, *, now: datetime) -> Reminder | None:
    """The reminder to show now, if any; snoozing is the caller's business."""
    ar = rules.advice
    last = signals.last
    if signals.open_test is not None:
        return Reminder("resume", f"resume:{signals.open_test}")
    if last is None:
        return Reminder("never", "never")
    days = (now - last.finished_at).days
    if (
        days >= ar.retest_min_days
        and last.total
        and last.learned / last.total >= ar.retest_learned_share
    ):
        reason: Reason = "progress"
    elif days >= ar.retest_days:
        reason = "age"
    else:
        return None
    return Reminder(reason, f"{reason}:{last.id}", days, last.level, last.learned, last.total)


async def load(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
) -> ReminderSignals:
    """May rebuild stale mastery rows first; the caller commits."""
    open_test = await session.scalar(
        select(PlacementSession.id)
        .where(PlacementSession.user_id == user_id, PlacementSession.status == "in_progress")
        .limit(1)
    )
    row = (
        await session.execute(
            select(PlacementSession.id, PlacementSession.finished_at, PlacementSession.result)
            .where(PlacementSession.user_id == user_id, PlacementSession.status == "done")
            .order_by(PlacementSession.finished_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return ReminderSignals(open_test, None)
    test_id, finished_at, result = row
    level: CefrLevel = result["cefr"]
    kc_ids = [kc.id for kc in catalog.kcs if kc.cefr == level]
    await mastery.ensure_current(session, user_id, rules=rules, catalog=catalog)
    learned = await session.scalar(
        select(func.count()).where(
            KCMastery.user_id == user_id,
            KCMastery.kc_id.in_(kc_ids),
            KCMastery.mastered_at.is_not(None),
        )
    )
    return ReminderSignals(
        open_test, LastTest(test_id, finished_at, level, learned or 0, len(kc_ids))
    )


async def current(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime | None = None,
) -> Reminder | None:
    """The reminder with its snooze; may rebuild stale mastery rows, the caller commits."""
    now = now or datetime.now(UTC)
    found = decide(await load(session, user_id, rules=rules, catalog=catalog), rules, now=now)
    if found is None:
        return None
    dismissed = await session.scalar(
        select(ReminderDismissal.dismissed_at).where(
            ReminderDismissal.user_id == user_id, ReminderDismissal.key == found.key
        )
    )
    quiet = timedelta(days=rules.advice.reminder_snooze_days)
    return replace(found, snoozed=dismissed is not None and now - dismissed < quiet)


async def dismiss(
    session: AsyncSession, user_id: uuid.UUID, key: str, *, now: datetime | None = None
) -> None:
    """Record "Not now" on `key` as of `now`; does not commit."""
    now = now or datetime.now(UTC)
    await session.execute(
        insert(ReminderDismissal)
        .values(user_id=user_id, key=key, dismissed_at=now)
        .on_conflict_do_update(
            index_elements=[ReminderDismissal.user_id, ReminderDismissal.key],
            set_={"dismissed_at": now},
        )
    )
