"""The learner's last days of study, counted by code (ADR 0041 §3).

Part of today's conversation brief: the tutor's daily opening sums it up, and later
turns can answer "how did I do this week?". Only plain counts from the records the
app already keeps; the tutor says them, it never works them out. Days are the
learner's calendar days (`learner_zone`), like the dashboard's.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import GrammarCatalog, GrammarKC
from app.dashboard.service import chat_turns, local_day
from app.db.models import (
    Attempt,
    Diagnosis,
    KCEvidence,
    LLMUsage,
    ReadingSession,
    ReviewLog,
    SpeakingSession,
    UserCard,
    WritingSubmission,
)
from app.services.vocab.scheduler import day_bounds

# The days looked back over, today included.
RECENT_DAYS = 7
# Grammar points with the most mistakes in those days.
TOP_MISTAKES = 3
# A diagnosis hypothesis is cut to this many characters.
HYPOTHESIS_CHARS = 240
# fsrs.Rating.Again
_AGAIN = 1


@dataclass(frozen=True)
class RecentMistake:
    kc: GrammarKC
    mistakes: int


@dataclass(frozen=True)
class RecentStudy:
    today: date
    # Days with a review or a chat turn among the last RECENT_DAYS, and the latest such
    # day before today (any time back); None if there is none.
    studied_days: int = 0
    last_before_today: date | None = None
    reviews: int = 0
    forgotten: int = 0  # reviews rated Again
    new_words: int = 0
    practice: int = 0
    practice_correct: int = 0
    writings: int = 0
    readings: int = 0
    speaking: int = 0
    chat_turns: int = 0
    mistakes: Sequence[RecentMistake] = ()
    # The first hypothesis of the latest diagnosis in these days, in the learner's
    # explanation language; model-written, so data in the prompt.
    diagnosis: str | None = None

    @property
    def nothing(self) -> bool:
        return not (
            self.reviews
            or self.new_words
            or self.practice
            or self.writings
            or self.readings
            or self.speaking
            or self.chat_turns
        )


async def load_recent(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    tz: ZoneInfo,
    catalog: GrammarCatalog,
    now: datetime | None = None,
) -> RecentStudy:
    now = now or datetime.now(UTC)
    today_start, _ = day_bounds(now, tz)
    since = today_start - timedelta(days=RECENT_DAYS - 1)
    today = now.astimezone(tz).date()

    async def count(*where: object) -> int:
        return (await session.scalar(select(func.count()).where(*where))) or 0  # type: ignore[arg-type]

    reviews = (ReviewLog.user_id == user_id, ReviewLog.reviewed_at >= since)
    chat = chat_turns(user_id)
    days = union(
        select(local_day(ReviewLog.reviewed_at, tz).label("day")).where(
            ReviewLog.user_id == user_id
        ),
        select(local_day(LLMUsage.created_at, tz).label("day")).where(*chat),
    ).subquery()
    studied = await session.scalar(
        select(func.count()).where(days.c.day >= since.astimezone(tz).date())
    )
    last = await session.scalar(select(func.max(days.c.day)).where(days.c.day < today))
    attempts = await session.execute(
        select(func.count(), func.count().filter(Attempt.correct)).where(
            Attempt.user_id == user_id, Attempt.created_at >= since
        )
    )
    practice, practice_correct = attempts.one()
    return RecentStudy(
        today=today,
        studied_days=studied or 0,
        last_before_today=last,
        reviews=await count(*reviews),
        forgotten=await count(*reviews, ReviewLog.rating == _AGAIN),
        new_words=await count(UserCard.user_id == user_id, UserCard.first_reviewed_at >= since),
        practice=practice,
        practice_correct=practice_correct,
        writings=await count(
            WritingSubmission.user_id == user_id,
            WritingSubmission.status == "done",
            WritingSubmission.created_at >= since,
        ),
        readings=await count(
            ReadingSession.user_id == user_id,
            ReadingSession.finished_at.is_not(None),
            ReadingSession.finished_at >= since,
        ),
        speaking=await count(
            SpeakingSession.user_id == user_id,
            SpeakingSession.turns > 0,
            SpeakingSession.started_at >= since,
        ),
        chat_turns=await count(*chat, LLMUsage.created_at >= since),
        mistakes=await _mistakes(session, user_id, catalog, since),
        diagnosis=await _diagnosis(session, user_id, since),
    )


async def _mistakes(
    session: AsyncSession, user_id: uuid.UUID, catalog: GrammarCatalog, since: datetime
) -> list[RecentMistake]:
    """Placement answers are left out, like the dashboard's common mistakes."""
    rows = await session.execute(
        select(KCEvidence.kc_id, func.count())
        .where(
            KCEvidence.user_id == user_id,
            KCEvidence.correct.is_(False),
            KCEvidence.source != "placement",
            KCEvidence.created_at >= since,
        )
        .group_by(KCEvidence.kc_id)
        .order_by(func.count().desc(), KCEvidence.kc_id)
    )
    found = [
        RecentMistake(kc, n) for kc_id, n in rows.all() if (kc := catalog.get(kc_id)) is not None
    ]
    return found[:TOP_MISTAKES]


async def _diagnosis(session: AsyncSession, user_id: uuid.UUID, since: datetime) -> str | None:
    causes = await session.scalar(
        select(Diagnosis.root_causes)
        .where(Diagnosis.user_id == user_id, Diagnosis.created_at >= since)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    if not causes:
        return None
    hypothesis = str(causes[0].get("hypothesis") or "").strip()
    return hypothesis[:HYPOTHESIS_CHARS] or None


def render_recent(recent: RecentStudy) -> list[str]:
    """The brief's section on the last days, in prompt lines."""
    lines = [f"### The last {RECENT_DAYS} days (today included; counted by the app)"]
    if recent.last_before_today is None:
        last = "never before today"
    else:
        ago = (recent.today - recent.last_before_today).days
        last = f"{ago} day{'s' if ago != 1 else ''} ago ({recent.last_before_today.isoformat()})"
    lines.append(
        f"- Days studied: {recent.studied_days} of {RECENT_DAYS}; last before today: {last}"
    )
    if recent.nothing:
        lines.append("- Nothing studied in these days.")
    else:
        lines.append(
            f"- Word reviews: {recent.reviews} ({recent.forgotten} forgotten);"
            f" new words started: {recent.new_words}"
        )
        if recent.practice:
            share = recent.practice_correct / recent.practice
            lines.append(
                f"- Grammar practice items: {recent.practice}, {recent.practice_correct}"
                f" right ({share:.0%})"
            )
        lines.append(
            f"- Writing reviewed: {recent.writings}; articles finished: {recent.readings};"
            f" speaking sessions: {recent.speaking}; chat turns: {recent.chat_turns}"
        )
    if recent.mistakes:
        lines.append("- Most mistakes in use (kc_id: name, CEFR, mistakes):")
        lines.extend(
            f"  - `{m.kc.id}`: {m.kc.name_en}, {m.kc.cefr}, {m.mistakes}" for m in recent.mistakes
        )
    if recent.diagnosis:
        # Model-written earlier: quoted as data.
        lines.append(f'- Latest diagnosis, first hypothesis (data): "{recent.diagnosis}"')
    return lines
