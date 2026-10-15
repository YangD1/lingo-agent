"""The grammar course (ADR 0044 §2): one lesson per KC, in a fixed order, each with a
state worked out from the learner model on read.

The order is by CEFR level, and within a level a topological sort on prerequisites that
keeps the catalog's order among KCs that do not depend on each other. Nothing about the
course is stored: a lesson's state comes from kc_mastery, the latest pass quiz and
whether the learner has opened the lesson, so deleting evidence moves a lesson back.
Only the score of a pass quiz and p_mastery decide that a lesson is passed; a model
never does.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.bkt import prior
from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel, GrammarCatalog, GrammarKC
from app.adaptive.rules import Rules
from app.db.models import Attempt, Conversation, Exercise, ExerciseSet, KCMastery
from app.memory.service import get_profile

type LessonState = Literal["passed", "review", "learning", "available", "locked"]


@dataclass(frozen=True, slots=True)
class KCProgress:
    """What the course reads about one KC besides the catalog."""

    p_mastery: float
    learned: bool = False
    due: datetime | None = None
    # The learner has a lesson conversation or a quiz on the KC.
    started: bool = False
    # Share of items answered right in the latest finished pass quiz.
    quiz_score: float | None = None


@dataclass(frozen=True, slots=True)
class Lesson:
    number: int
    kc: GrammarKC
    state: LessonState
    p_mastery: float
    quiz_score: float | None
    # Prerequisites that keep a locked lesson locked.
    blocked_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Course:
    # The learner's placement level; None before a placement test.
    level: CefrLevel | None
    lessons: list[Lesson]
    # KC id of the lesson to continue with; None when every lesson is passed.
    current: str | None

    def lesson(self, kc_id: str) -> Lesson | None:
        return next((lesson for lesson in self.lessons if lesson.kc.id == kc_id), None)

    def next_after(self, kc_id: str) -> Lesson | None:
        """The first lesson after `kc_id` in course order that is not passed yet."""
        ids = [lesson.kc.id for lesson in self.lessons]
        if kc_id not in ids:
            return None
        return next(
            (
                lesson
                for lesson in self.lessons[ids.index(kc_id) + 1 :]
                if lesson.state in ("learning", "available")
            ),
            None,
        )


def order(catalog: GrammarCatalog) -> list[GrammarKC]:
    """Every KC in course order (see the module docstring)."""
    out: list[GrammarKC] = []
    for level in CEFR_LEVELS:
        pending = [kc for kc in catalog.kcs if kc.cefr == level]
        ids = {kc.id for kc in pending}
        done: set[str] = set()
        while pending:
            ready = next(
                kc for kc in pending if all(p in done or p not in ids for p in kc.prerequisites)
            )
            out.append(ready)
            done.add(ready.id)
            pending.remove(ready)
    return out


def _below(kc: GrammarKC, level: CefrLevel | None) -> bool:
    return level is not None and CEFR_LEVELS.index(kc.cefr) < CEFR_LEVELS.index(level)


def build(
    catalog: GrammarCatalog,
    progress: Mapping[str, KCProgress],
    *,
    level: CefrLevel | None,
    now: datetime,
    rules: Rules,
) -> Course:
    """The course from what is known about each KC; KCs missing from `progress` have
    no evidence and take the prior for the learner's level."""
    course = rules.course
    passed: dict[str, bool] = {}
    # Lets the lessons that depend on it open: passed, or below the learner's level
    # and not weak (the placement test says it is known well enough to build on).
    cleared: dict[str, bool] = {}
    lessons: list[Lesson] = []
    current: str | None = None
    for number, kc in enumerate(order(catalog), start=1):
        known = progress.get(kc.id) or KCProgress(prior(kc.cefr, level, rules))
        p = known.p_mastery
        is_passed = (
            known.learned
            or (
                known.quiz_score is not None
                and known.quiz_score >= course.pass_score
                and p >= course.pass_p
            )
            or (_below(kc, level) and p >= course.pass_p)
        )
        passed[kc.id] = is_passed
        cleared[kc.id] = is_passed or (_below(kc, level) and p >= rules.bkt.weak)
        blocked = tuple(
            p_id for p_id in kc.prerequisites if p_id in catalog and not cleared.get(p_id, True)
        )
        state: LessonState
        if is_passed:
            due = known.learned and known.due is not None and known.due <= now
            state = "review" if due or p < rules.bkt.weak else "passed"
        elif known.started:
            state = "learning"
        elif blocked:
            state = "locked"
        else:
            state = "available"
        # A gap below the learner's level comes first only when it is weak.
        if (
            current is None
            and state in ("learning", "available")
            and (not _below(kc, level) or p < rules.bkt.weak)
        ):
            current = kc.id
        lessons.append(Lesson(number, kc, state, p, known.quiz_score, blocked))
    return Course(level, lessons, current)


async def quiz_scores(
    session: AsyncSession, user_id: uuid.UUID, kc_ids: Sequence[str] | None = None
) -> dict[str, float]:
    """Per KC, the score of the latest finished pass quiz: first answers right over
    the quiz's items."""
    latest = (
        select(ExerciseSet.id, ExerciseSet.focus_kc_id)
        .where(
            ExerciseSet.user_id == user_id,
            ExerciseSet.origin == "quiz",
            ExerciseSet.quiz_purpose == "quiz",
            ExerciseSet.status == "done",
            ExerciseSet.focus_kc_id.is_not(None),
        )
        .ext(distinct_on(ExerciseSet.focus_kc_id))
        .order_by(ExerciseSet.focus_kc_id, ExerciseSet.finished_at.desc(), ExerciseSet.id)
    )
    if kc_ids is not None:
        latest = latest.where(ExerciseSet.focus_kc_id.in_(kc_ids))
    sets = {set_id: cast(str, kc_id) for set_id, kc_id in (await session.execute(latest)).all()}
    if not sets:
        return {}
    rows = await session.execute(
        select(Exercise.set_id, Exercise.id, Attempt.correct)
        .outerjoin(Attempt, Attempt.exercise_id == Exercise.id)
        .where(Exercise.set_id.in_(sets), Exercise.status == "ok")
        .order_by(Exercise.set_id, Exercise.id, Attempt.id)
    )
    first: dict[int, tuple[uuid.UUID, bool]] = {}
    for set_id, exercise_id, correct in rows.all():
        first.setdefault(exercise_id, (set_id, bool(correct)))
    totals: dict[uuid.UUID, list[int]] = {}
    for set_id, correct in first.values():
        counts = totals.setdefault(set_id, [0, 0])
        counts[0] += int(correct)
        counts[1] += 1
    return {sets[s]: right / total for s, (right, total) in totals.items() if total}


async def load(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime,
) -> Course:
    """The learner's course; may rebuild stale mastery rows but does not commit."""
    await mastery.ensure_current(session, user_id, rules=rules, catalog=catalog)
    profile = await get_profile(session, user_id)
    level = cast(CefrLevel | None, profile.cefr_level if profile else None)
    rows = await session.scalars(
        select(KCMastery).where(KCMastery.user_id == user_id, KCMastery.kind == "grammar")
    )
    lessons = await session.scalars(
        select(Conversation.focus_kc_id).where(
            Conversation.user_id == user_id,
            Conversation.purpose == "lesson",
            Conversation.focus_kc_id.is_not(None),
        )
    )
    quizzed = await session.scalars(
        select(ExerciseSet.focus_kc_id).where(
            ExerciseSet.user_id == user_id,
            ExerciseSet.origin == "quiz",
            ExerciseSet.focus_kc_id.is_not(None),
        )
    )
    started = {cast(str, kc_id) for kc_id in [*lessons.all(), *quizzed.all()]}
    scores = await quiz_scores(session, user_id)
    progress: dict[str, KCProgress] = {
        row.kc_id: KCProgress(
            row.p_mastery,
            learned=row.mastered_at is not None,
            due=row.due,
            started=row.kc_id in started,
            quiz_score=scores.get(row.kc_id),
        )
        for row in rows
        if row.kc_id in catalog
    }
    for kc_id in started - progress.keys():
        kc = catalog.get(kc_id)
        if kc is not None:
            progress[kc_id] = KCProgress(
                prior(kc.cefr, level, rules), started=True, quiz_score=scores.get(kc_id)
            )
    return build(catalog, progress, level=level, now=now, rules=rules)
