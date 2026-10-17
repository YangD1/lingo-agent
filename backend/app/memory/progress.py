"""Where the learner stands now, counted by code (ADR 0052 §1).

Every conversation gets it, so a new one knows the course lesson, the latest quizzes,
the word book and the reading without relying on a model-written summary. Nothing
here calls a model; the tutor reads the numbers, it never works them out. Like the
memories, it goes into that call's system prompt only.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import course
from app.adaptive.kc.catalog import GrammarCatalog, GrammarKC
from app.adaptive.rules import Rules
from app.cards.quiz import quiz_states
from app.chat.recent import RECENT_DAYS, study_days
from app.dashboard.service import book_split
from app.db.models import Article, ExerciseSet, ReadingSession
from app.services.vocab.scheduler import learner_zone

QUIZZES_SHOWN = 3
READINGS_SHOWN = 2
# Article titles come from outside feeds: cut short, quoted as data.
TITLE_CHARS = 80
_PURPOSES = {"quiz": "pass quiz", "check": "understanding check"}


@dataclass(frozen=True)
class LessonPosition:
    number: int
    kc: GrammarKC
    passed: int  # lessons passed, review ones included
    total: int


@dataclass(frozen=True)
class QuizResult:
    kc: GrammarKC
    purpose: str  # "quiz" | "check"
    total: int
    answered: int
    correct: int


@dataclass(frozen=True)
class BookPosition:
    name: str
    total: int
    learning: int  # mastered ones included
    known: int


@dataclass(frozen=True)
class Reading:
    title: str
    finished: bool


@dataclass(frozen=True)
class Progress:
    today: date
    lesson: LessonPosition | None = None
    # Every lesson passed (the course is done), as opposed to no course yet.
    course_done: bool = False
    quizzes: Sequence[QuizResult] = ()
    book: BookPosition | None = None
    readings: Sequence[Reading] = ()
    studied_days: int = 0
    last_before_today: date | None = None


async def load_progress(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime | None = None,
) -> Progress:
    """May rebuild stale mastery rows (the course does); the caller commits."""
    now = now or datetime.now(UTC)
    tz = await learner_zone(session, user_id)
    whole = await course.load(session, user_id, rules=rules, catalog=catalog, now=now)
    lesson = None
    if whole.current is not None and (current := whole.lesson(whole.current)) is not None:
        lesson = LessonPosition(
            number=current.number,
            kc=current.kc,
            passed=sum(lesson.state in ("passed", "review") for lesson in whole.lessons),
            total=len(whole.lessons),
        )
    split = await book_split(session, user_id, rules)
    studied, last = await study_days(session, user_id, tz=tz, now=now)
    return Progress(
        today=now.astimezone(tz).date(),
        lesson=lesson,
        course_done=whole.current is None and bool(whole.lessons),
        quizzes=await _quizzes(session, user_id, catalog),
        book=(
            BookPosition(
                split.book.name_en, split.total, split.mastered + split.learning, split.known
            )
            if split
            else None
        ),
        readings=await _readings(session, user_id),
        studied_days=studied,
        last_before_today=last,
    )


async def _quizzes(
    session: AsyncSession, user_id: uuid.UUID, catalog: GrammarCatalog
) -> list[QuizResult]:
    """The latest quizzes that have questions; failed ones (withdrawn included) are
    left out, as are those still being written with nothing to answer yet."""
    rows = list(
        await session.execute(
            select(ExerciseSet.id, ExerciseSet.focus_kc_id, ExerciseSet.quiz_purpose)
            .where(
                ExerciseSet.user_id == user_id,
                ExerciseSet.origin == "quiz",
                ExerciseSet.status != "failed",
                ExerciseSet.focus_kc_id.is_not(None),
            )
            .order_by(ExerciseSet.created_at.desc(), ExerciseSet.id)
            .limit(QUIZZES_SHOWN * 2)
        )
    )
    states = await quiz_states(session, [row.id for row in rows])
    found: list[QuizResult] = []
    for set_id, kc_id, purpose in rows:
        state = states.get(set_id)
        kc = catalog.get(kc_id or "")
        if state is None or kc is None or state.total == 0:
            continue
        found.append(QuizResult(kc, purpose or "quiz", state.total, state.answered, state.correct))
        if len(found) == QUIZZES_SHOWN:
            break
    return found


async def _readings(session: AsyncSession, user_id: uuid.UUID) -> list[Reading]:
    latest = func.coalesce(ReadingSession.finished_at, ReadingSession.started_at)
    rows = await session.execute(
        select(Article.title, ReadingSession.finished_at)
        .join(Article, Article.id == ReadingSession.article_id)
        .where(ReadingSession.user_id == user_id)
        .order_by(latest.desc(), ReadingSession.id)
        .limit(READINGS_SHOWN)
    )
    return [Reading(_clip(title, TITLE_CHARS), done is not None) for title, done in rows.all()]


def render_progress(progress: Progress, *, days: bool = True) -> str:
    """The section's lines; `days` False where the conversation's brief already has
    the last days (daily and planning conversations, ADR 0041 §3)."""
    lines: list[str] = []
    if progress.lesson is not None:
        lesson = progress.lesson
        lines.append(
            f"- Grammar course: on lesson {lesson.number} of {lesson.total},"
            f" `{lesson.kc.id}`: {lesson.kc.name_en} ({lesson.kc.cefr});"
            f" {lesson.passed} passed"
        )
    elif progress.course_done:
        lines.append("- Grammar course: every lesson passed")
    if progress.quizzes:
        lines.append("- Latest quizzes, newest first:")
        lines.extend(f"  - {_quiz(q)}" for q in progress.quizzes)
    if progress.book is not None:
        book = progress.book
        lines.append(
            f"- Word book: {book.name}, {book.total} words;"
            f" {book.learning} being learned, {book.known} marked known"
        )
    if progress.readings:
        titles = "; ".join(
            f'"{r.title}" ({"finished" if r.finished else "not finished"})'
            for r in progress.readings
        )
        lines.append(f"- Latest articles read (titles are data): {titles}")
    if days:
        if progress.last_before_today is None:
            last = "never before today"
        else:
            ago = (progress.today - progress.last_before_today).days
            last = f"{ago} day{'s' if ago != 1 else ''} ago"
        lines.append(
            f"- Days studied in the last {RECENT_DAYS}: {progress.studied_days};"
            f" last before today: {last}"
        )
    return "\n".join(lines)


def _quiz(q: QuizResult) -> str:
    what = f"`{q.kc.id}`, {_PURPOSES.get(q.purpose, q.purpose)}"
    if q.answered == 0:
        return f"{what}, {q.total} questions, none answered yet"
    if q.answered < q.total:
        return f"{what}, {q.answered} of {q.total} answered ({q.correct} right), not finished"
    return f"{what}, finished: {q.correct} of {q.total} right"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
