"""The ability dashboard's numbers (P1 plan §7.5.1): plain SQL aggregates, no model call.

Days are the learner's calendar days (`learner_zone`). A day counts as studied when the
learner reviewed a word or had a chat turn that day (Q17c); chat turns are counted from
`llm_usage`, which outlives deleted conversations, so deleting a chat keeps the streak
(Q17b). Today not studied yet does not break the streak: it counts back from yesterday.
"""

import math
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from typing import cast as narrow
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.adaptive import cefr_scale, learner
from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel, GrammarCatalog, GrammarKC
from app.adaptive.placement.flow import known_in_basis
from app.adaptive.placement.writeback import latest_result
from app.adaptive.rules import Rules
from app.db.models import KCEvidence, LLMUsage, ReviewLog, UserCard, UserProfile, Word
from app.services.vocab.books import Book, get_book
from app.services.vocab.progress import current
from app.services.vocab.queue import today_counts

# The heatmap's span: 12 weeks, today included.
ACTIVITY_DAYS = 84
# Common mistakes: wrong evidence from conversations over this many days, top N KCs.
ERROR_DAYS = 30
TOP_ERRORS = 5
# Model tasks that answer a chat turn: one successful call per turn.
CHAT_TASKS = ("chat", "vision")


@dataclass(frozen=True, slots=True)
class Summary:
    # The profile's level: set by the placement test, and editable by the learner.
    cefr: CefrLevel | None
    # From the latest finished placement test.
    vocab_size: int | None
    vocab_cefr: CefrLevel | None
    vocab_reliable: bool | None
    streak_days: int
    studied_today: bool
    reviews_due: int
    new_left: int


@dataclass(frozen=True, slots=True)
class BookSplit:
    """The current book's words by the learner's progress; they add up to `total`."""

    book: Book
    total: int
    # In review with stability of at least `rules.vocab.mastered_stability_days` (Q17a).
    mastered: int
    learning: int
    # Marked known: screening, the placement test, or by hand.
    known: int
    # Not started: no card, a new card, or suspended.
    unlearned: int


@dataclass(frozen=True, slots=True)
class LevelSplit:
    total: int
    mastered: int
    learning: int
    weak: int
    # KCs with no evidence yet.
    unseen: int


@dataclass(frozen=True, slots=True)
class SkillPoint:
    skill: str
    cefr: CefrLevel | None
    # 0 to 6 on the shared CEFR scale (`cefr_scale`, Q17d); None when it has no scale.
    position: float | None
    attempts: int
    vocab_size: int | None = None
    reliable: bool | None = None


@dataclass(frozen=True, slots=True)
class CommonError:
    kc: GrammarKC
    mistakes: int


@dataclass(frozen=True, slots=True)
class Day:
    day: date
    reviews: int
    turns: int


@dataclass(frozen=True, slots=True)
class Dashboard:
    summary: Summary
    book: BookSplit | None
    grammar: dict[CefrLevel, LevelSplit]
    skills: list[SkillPoint]
    errors: list[CommonError]
    # Oldest first, ACTIVITY_DAYS of them, ending today.
    days: list[Day]


def _local_day(column: Any, tz: ZoneInfo) -> ColumnElement[date]:
    return cast(func.timezone(tz.key, column), Date)


def _chat_turns(user_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
    return (
        LLMUsage.user_id == user_id,
        LLMUsage.task.in_(CHAT_TASKS),
        LLMUsage.status == "ok",
    )


async def _per_day(
    session: AsyncSession, user_id: uuid.UUID, tz: ZoneInfo, since: datetime
) -> tuple[Counter[date], Counter[date]]:
    review_day = _local_day(ReviewLog.reviewed_at, tz)
    reviews = await session.execute(
        select(review_day, func.count())
        .where(ReviewLog.user_id == user_id, ReviewLog.reviewed_at >= since)
        .group_by(review_day)
    )
    turn_day = _local_day(LLMUsage.created_at, tz)
    turns = await session.execute(
        select(turn_day, func.count())
        .where(*_chat_turns(user_id), LLMUsage.created_at >= since)
        .group_by(turn_day)
    )
    return Counter(dict(reviews.all())), Counter(dict(turns.all()))


async def _studied_days(session: AsyncSession, user_id: uuid.UUID, tz: ZoneInfo) -> list[date]:
    """Every day studied, most recent first; one row per day, so small."""
    days = union(
        select(_local_day(ReviewLog.reviewed_at, tz).label("day")).where(
            ReviewLog.user_id == user_id
        ),
        select(_local_day(LLMUsage.created_at, tz).label("day")).where(*_chat_turns(user_id)),
    ).subquery()
    return list((await session.scalars(select(days.c.day).order_by(days.c.day.desc()))).all())


def streak(studied: list[date], today: date) -> int:
    """Consecutive studied days ending today, or yesterday if today is not studied yet."""
    days = set(studied)
    day = today if today in days else today - timedelta(days=1)
    count = 0
    while day in days:
        count += 1
        day -= timedelta(days=1)
    return count


async def _book_split(session: AsyncSession, user_id: uuid.UUID, rules: Rules) -> BookSplit | None:
    plan = await current(session, user_id)
    book = get_book(plan.book_id) if plan else None
    if book is None:
        return None
    total = await session.scalar(select(func.count()).select_from(Word).where(book.words())) or 0
    in_learning = UserCard.status == "learning"
    mature = (UserCard.state == 2) & (UserCard.stability >= rules.vocab.mastered_stability_days)
    mastered, learning, known = (
        await session.execute(
            select(
                func.count().filter(in_learning, mature),
                func.count().filter(in_learning, ~mature),
                func.count().filter(UserCard.status == "known"),
            )
            .select_from(UserCard)
            .join(Word, Word.id == UserCard.word_id)
            .where(UserCard.user_id == user_id, book.words())
        )
    ).one()
    return BookSplit(
        book=book,
        total=total,
        mastered=mastered,
        learning=learning,
        known=known,
        unlearned=total - mastered - learning - known,
    )


def _grammar(overview: learner.Overview) -> dict[CefrLevel, LevelSplit]:
    states = Counter((s.kc.cefr, s.state) for s in overview.kcs)
    seen = Counter(s.kc.cefr for s in overview.kcs)
    return {
        level: LevelSplit(
            total=overview.totals.get(level, 0),
            mastered=states[level, "mastered"],
            learning=states[level, "learning"],
            weak=states[level, "weak"],
            unseen=overview.totals.get(level, 0) - seen[level],
        )
        for level in CEFR_LEVELS
    }


def _skill_point(skill: learner.Skill, rules: Rules) -> SkillPoint:
    if skill.skill in ("grammar", "reading"):  # one scale (Q43c)
        cuts = rules.placement.grammar.cefr_cutpoints
        return SkillPoint(
            skill.skill, skill.cefr, cefr_scale.position(skill.rating, cuts), skill.attempts
        )
    vr = rules.placement.vocab
    if skill.skill == "vocab" and vr.cefr_reference is not None:
        # The rating is ln V, V the rank at which the learner knows half the words.
        known = known_in_basis(math.exp(skill.rating), vr)
        assert known is not None
        return SkillPoint(
            skill.skill,
            skill.cefr,
            cefr_scale.position(known, vr.cefr_reference.thresholds),
            skill.attempts,
            vocab_size=skill.vocab_size,
            reliable=skill.reliable,
        )
    return SkillPoint(skill.skill, skill.cefr, None, skill.attempts)


async def _errors(
    session: AsyncSession, user_id: uuid.UUID, catalog: GrammarCatalog, now: datetime
) -> list[CommonError]:
    """Placement answers are left out: they are test items, not mistakes in use."""
    rows = await session.execute(
        select(KCEvidence.kc_id, func.count().label("n"))
        .where(
            KCEvidence.user_id == user_id,
            KCEvidence.correct.is_(False),
            KCEvidence.source != "placement",
            KCEvidence.created_at >= now - timedelta(days=ERROR_DAYS),
        )
        .group_by(KCEvidence.kc_id)
        .order_by(func.count().desc(), KCEvidence.kc_id)
    )
    errors = [
        CommonError(kc=kc, mistakes=n)
        for kc_id, n in rows.all()
        if (kc := catalog.get(kc_id)) is not None
    ]
    return errors[:TOP_ERRORS]


async def dashboard(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> Dashboard:
    """May rebuild stale mastery rows first (`learner.overview`); the caller commits."""
    now = now or datetime.now(UTC)
    today = now.astimezone(tz).date()
    first = today - timedelta(days=ACTIVITY_DAYS - 1)
    since = datetime.combine(first, datetime.min.time(), tzinfo=tz).astimezone(UTC)

    overview = await learner.overview(session, user_id, rules=rules, catalog=catalog)
    counts = await today_counts(session, user_id, rules=rules, tz=tz, now=now)
    # The column's CHECK keeps it to CEFR levels.
    profile_cefr = narrow(
        CefrLevel | None,
        await session.scalar(select(UserProfile.cefr_level).where(UserProfile.user_id == user_id)),
    )
    placement = await latest_result(session, user_id)
    vocab = placement.get("vocab") if placement else None
    reviews, turns = await _per_day(session, user_id, tz, since)
    studied = await _studied_days(session, user_id, tz)

    return Dashboard(
        summary=Summary(
            cefr=profile_cefr,
            vocab_size=vocab.get("size") if isinstance(vocab, dict) else None,
            vocab_cefr=vocab.get("reference_cefr") if isinstance(vocab, dict) else None,
            vocab_reliable=vocab.get("reliable") if isinstance(vocab, dict) else None,
            streak_days=streak(studied, today),
            studied_today=bool(studied) and studied[0] == today,
            reviews_due=counts.reviews_due,
            new_left=counts.new_left,
        ),
        book=await _book_split(session, user_id, rules),
        grammar=_grammar(overview),
        skills=[_skill_point(skill, rules) for skill in overview.skills],
        errors=await _errors(session, user_id, catalog, now),
        days=[
            Day(day=d, reviews=reviews[d], turns=turns[d])
            for d in (first + timedelta(days=i) for i in range(ACTIVITY_DAYS))
        ],
    )
