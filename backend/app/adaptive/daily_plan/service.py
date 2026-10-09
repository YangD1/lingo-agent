"""A learner's plan for today in the database (ADR 0027): drafted the first time it is
read, confirmed / declined / undone by the learner; progress counted from each module's
records of the learner's local day."""

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.daily_plan.algorithm import (
    ItemKind,
    PlanChoice,
    PlanInputs,
    PlanItem,
    clamp,
    draft,
    items,
)
from app.adaptive.exercise import inputs as exercise_inputs
from app.adaptive.exercise.planner import candidates
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import Rules
from app.db.models import (
    ArticleVersion,
    DailyPlan,
    ExerciseSet,
    ReadingSession,
    ReviewLog,
    UserCard,
    UserProfile,
    WritingSubmission,
)
from app.services.news import feeds
from app.services.reading.versions import reading_level
from app.services.vocab.queue import today_counts
from app.services.vocab.scheduler import day_bounds, learner_zone

# Newest articles from the learner's feeds looked at for today's reading.
ARTICLES_LOOKED_AT = 30


class PlanStateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Progress:
    item: PlanItem
    # Reviews done, new words started; 0 or 1 for practice, reading and writing.
    done: int

    @property
    def target(self) -> int:
        return self.item.count if self.item.count is not None else 1

    @property
    def complete(self) -> bool:
        return self.done >= self.target


@dataclass(frozen=True, slots=True)
class PlanView:
    plan: DailyPlan
    inputs: PlanInputs
    choice: PlanChoice
    progress: tuple[Progress, ...]

    @property
    def minutes(self) -> float:
        return sum(p.item.minutes for p in self.progress)


def local_day(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


# --- what is open today -------------------------------------------------------------------


async def _practice_kc(
    session: AsyncSession, user_id: uuid.UUID, *, rules: Rules, now: datetime
) -> str | None:
    """The KC a practice set would start with: the weakest by priority, else the most
    overdue learned one; None when there is nothing to practise."""
    catalog = get_grammar_catalog()
    learner = await exercise_inputs.load(session, user_id, rules=rules, catalog=catalog, now=now)
    ranked = candidates(
        catalog,
        learner.states,
        learner_level=learner.level,
        now=now,
        rules=rules,
        boost=learner.boost,
    )
    if ranked.weak:
        return ranked.weak[0]
    due = [k for k in ranked.learned if (d := ranked.states[k].due) is not None and d <= now]
    return due[0] if due else None


async def _article(
    session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID, *, rules: Rules
) -> int | None:
    """The newest unread article from the learner's feeds, one already rewritten for
    their level first (no model call needed to open it)."""
    views = await feeds.list_articles(
        session, user_id, tenant_id, limit=ARTICLES_LOOKED_AT, before=None
    )
    ids = [v.article.id for v in views]
    if not ids:
        return None
    read = set(
        await session.scalars(
            select(ReadingSession.article_id).where(
                ReadingSession.user_id == user_id, ReadingSession.article_id.in_(ids)
            )
        )
    )
    unread = [i for i in ids if i not in read]
    if not unread:
        return None
    level = await reading_level(session, user_id, rules)
    ready = set(
        await session.scalars(
            select(ArticleVersion.article_id).where(
                ArticleVersion.tenant_id == tenant_id,
                ArticleVersion.level == level,
                ArticleVersion.status == "ready",
                ArticleVersion.article_id.in_(unread),
            )
        )
    )
    return next((i for i in unread if i in ready), unread[0])


async def read_inputs(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    rules: Rules,
    tz: ZoneInfo,
    now: datetime,
) -> PlanInputs:
    minutes = await session.scalar(
        select(UserProfile.daily_minutes).where(UserProfile.user_id == user_id)
    )
    counts = await today_counts(session, user_id, rules=rules, tz=tz, now=now)
    last_essay = await session.scalar(
        select(func.max(WritingSubmission.created_at)).where(WritingSubmission.user_id == user_id)
    )
    days_since_writing = (
        (local_day(now, tz) - local_day(last_essay, tz)).days if last_essay else None
    )
    return PlanInputs(
        minutes=minutes,
        reviews_due=counts.reviews_due,
        new_left=counts.new_left,
        practice_kc=await _practice_kc(session, user_id, rules=rules, now=now),
        article_id=await _article(session, user_id, tenant_id, rules=rules),
        days_since_writing=days_since_writing,
    )


# --- stored plans -------------------------------------------------------------------------


def _choice(plan: DailyPlan) -> PlanChoice:
    return PlanChoice(**plan.choice)


def _inputs(plan: DailyPlan) -> PlanInputs:
    return PlanInputs(**plan.limits)


def _as_json(value: PlanChoice | PlanInputs) -> dict[str, Any]:
    return dataclasses.asdict(value)


async def today(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    rules: Rules,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> DailyPlan:
    """Today's plan, drafted on first read (Q48a); its numbers then stay (Q48e). Commits."""
    now = now or datetime.now(UTC)
    day = local_day(now, tz)
    found = await session.scalar(
        select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.day == day)
    )
    if found is not None:
        return found
    inputs = await read_inputs(session, user_id, tenant_id, rules=rules, tz=tz, now=now)
    # Two first reads at once: the second insert is dropped and both read the same row.
    await session.execute(
        insert(DailyPlan)
        .values(
            user_id=user_id,
            day=day,
            choice=_as_json(draft(inputs, rules)),
            limits=_as_json(inputs),
            status="proposed",
        )
        .on_conflict_do_nothing(index_elements=["user_id", "day"])
    )
    await session.commit()
    plan = await session.scalar(
        select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.day == day)
    )
    assert plan is not None
    return plan


async def current(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    rules: Rules,
    now: datetime | None = None,
) -> DailyPlan:
    """The learner's latest plan if it is from about today, else today's in their
    profile's zone; commits. For chat turns, which carry no browser time zone: the
    dashboard has usually drafted today's plan in the browser's zone already."""
    now = now or datetime.now(UTC)
    recent = await session.scalar(
        select(DailyPlan)
        .where(DailyPlan.user_id == user_id, DailyPlan.day >= now.date() - timedelta(days=1))
        .order_by(DailyPlan.day.desc())
        .limit(1)
    )
    if recent is not None:
        return recent
    zone = await learner_zone(session, user_id)
    return await today(session, user_id, tenant_id, rules=rules, tz=zone, now=now)


async def _done(
    session: AsyncSession, user_id: uuid.UUID, *, tz: ZoneInfo, now: datetime
) -> dict[ItemKind, int]:
    """What the learner did today, whether or not they came from the plan (Q48d)."""
    start, end = day_bounds(now, tz)
    # Reviews of words started before today: today's new words are their own item.
    reviews = await session.scalar(
        select(func.count())
        .select_from(ReviewLog)
        .join(UserCard, UserCard.id == ReviewLog.card_id)
        .where(
            ReviewLog.user_id == user_id,
            ReviewLog.reviewed_at >= start,
            ReviewLog.reviewed_at < end,
            UserCard.first_reviewed_at < start,
        )
    )
    new_words = await session.scalar(
        select(func.count())
        .select_from(UserCard)
        .where(
            UserCard.user_id == user_id,
            UserCard.first_reviewed_at >= start,
            UserCard.first_reviewed_at < end,
        )
    )
    practice = await session.scalar(
        select(func.count())
        .select_from(ExerciseSet)
        .where(
            ExerciseSet.user_id == user_id,
            ExerciseSet.status == "done",
            ExerciseSet.finished_at >= start,
            ExerciseSet.finished_at < end,
        )
    )
    reading = await session.scalar(
        select(func.count())
        .select_from(ReadingSession)
        .where(
            ReadingSession.user_id == user_id,
            ReadingSession.finished_at >= start,
            ReadingSession.finished_at < end,
        )
    )
    writing = await session.scalar(
        select(func.count())
        .select_from(WritingSubmission)
        .where(
            WritingSubmission.user_id == user_id,
            WritingSubmission.status != "failed",
            WritingSubmission.created_at >= start,
            WritingSubmission.created_at < end,
        )
    )
    return {
        "review": reviews or 0,
        "new_words": new_words or 0,
        "practice": min(practice or 0, 1),
        "reading": min(reading or 0, 1),
        "writing": min(writing or 0, 1),
    }


async def view(
    session: AsyncSession,
    plan: DailyPlan,
    *,
    rules: Rules,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> PlanView:
    now = now or datetime.now(UTC)
    inputs, choice = _inputs(plan), _choice(plan)
    done = await _done(session, plan.user_id, tz=tz, now=now)
    progress = tuple(Progress(i, done[i.kind]) for i in items(choice, inputs, rules))
    return PlanView(plan, inputs, choice, progress)


# --- the learner's decisions --------------------------------------------------------------


async def _own_today(
    session: AsyncSession, user_id: uuid.UUID, plan_id: uuid.UUID, *, tz: ZoneInfo, now: datetime
) -> DailyPlan:
    plan = await session.scalar(
        select(DailyPlan)
        .where(DailyPlan.id == plan_id, DailyPlan.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if plan is None:
        raise PlanStateError("plan_not_found", "No such plan.")
    if plan.day != local_day(now, tz):
        raise PlanStateError("plan_expired", "This plan was for another day.")
    return plan


async def confirm(
    session: AsyncSession,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
    *,
    rules: Rules,
    tz: ZoneInfo,
    choice: PlanChoice | None = None,
    now: datetime | None = None,
) -> DailyPlan:
    """Confirm the plan, adjusted to `choice` if given (Q48c, kept within what was open
    when it was drafted); commits. Confirming again without changes is a no-op."""
    now = now or datetime.now(UTC)
    plan = await _own_today(session, user_id, plan_id, tz=tz, now=now)
    if plan.status == "applied" and choice is None:
        return plan
    if plan.status != "proposed":
        raise PlanStateError("plan_not_pending", "This plan has already been handled.")
    if choice is not None:
        plan.choice = _as_json(clamp(choice, _inputs(plan), rules))
    plan.status = "applied"
    plan.decided_at = now
    await session.commit()
    return plan


async def decline(
    session: AsyncSession,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
    *,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> DailyPlan:
    now = now or datetime.now(UTC)
    plan = await _own_today(session, user_id, plan_id, tz=tz, now=now)
    if plan.status == "declined":
        return plan
    if plan.status != "proposed":
        raise PlanStateError("plan_not_pending", "This plan has already been handled.")
    plan.status = "declined"
    plan.decided_at = now
    await session.commit()
    return plan


async def undo(
    session: AsyncSession,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
    *,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> DailyPlan:
    """A confirmed plan goes back to waiting for confirmation (Q48f); commits."""
    now = now or datetime.now(UTC)
    plan = await _own_today(session, user_id, plan_id, tz=tz, now=now)
    if plan.status == "proposed":
        return plan
    if plan.status != "applied":
        raise PlanStateError("plan_not_applied", "Only a confirmed plan can be undone.")
    if plan.card_id is not None:
        # Undoing the card puts back the plan it replaced.
        raise PlanStateError("plan_from_card", "Undo this plan on the tutor's card.")
    plan.status = "proposed"
    plan.decided_at = None
    await session.commit()
    return plan
