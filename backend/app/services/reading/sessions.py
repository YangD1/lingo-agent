"""A learner reading an article: their session, quiz answers and the words marked in the
text (Q43a, Q43b, Q43d).

Quiz answers are graded in code against the version's key, which the page never gets
before answering. Only the first answers count: each moves the learner's reading
ability one Elo step (item difficulty = the version level's anchor, ADR 0010 §2), and
no grammar evidence is recorded (P2 plan §5.3).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.elo import update_ability
from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import Rules
from app.db.models import ArticleVersion, ReadingSession, SkillEstimate, UserCard
from app.services.reading import glossary
from app.services.reading.versions import ReadingError

SKILL = "reading"
# Four options: a blind guess is right a quarter of the time.
GUESS = 0.25


async def open_session(
    session: AsyncSession,
    user_id: uuid.UUID,
    article_id: int,
    *,
    version_id: uuid.UUID | None,
    level: CefrLevel,
    now: datetime,
) -> ReadingSession:
    """Start reading, or pick up where the learner left; commits. A session already
    answered keeps its version, whatever the learner's level is now."""
    statement = insert(ReadingSession).values(
        user_id=user_id,
        article_id=article_id,
        version_id=version_id,
        level=level,
        started_at=now,
        opened_at=now,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[ReadingSession.user_id, ReadingSession.article_id],
            set_={"opened_at": now},
        )
    )
    row = await session.scalar(
        select(ReadingSession)
        .where(ReadingSession.user_id == user_id, ReadingSession.article_id == article_id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    if row.answers is None and (row.version_id, row.level) != (version_id, level):
        row.version_id, row.level = version_id, level
    await session.commit()
    return row


async def get_session(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False
) -> ReadingSession:
    """The learner's own session; `lock` holds it so the first answers are graded once.
    Raises `ReadingError` for anyone else's."""
    statement = select(ReadingSession).where(
        ReadingSession.id == session_id, ReadingSession.user_id == user_id
    )
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement.execution_options(populate_existing=True))
    if row is None:
        raise ReadingError("session_not_found")
    return row


async def answered_version(
    session: AsyncSession, user_id: uuid.UUID, article_id: int
) -> uuid.UUID | None:
    """The version of an answered session, which the learner keeps reading."""
    return await session.scalar(
        select(ReadingSession.version_id).where(
            ReadingSession.user_id == user_id,
            ReadingSession.article_id == article_id,
            ReadingSession.answers.is_not(None),
        )
    )


@dataclass(frozen=True, slots=True)
class Result:
    choice: int
    correct: bool
    answer: int
    evidence: str


def results(version: ArticleVersion, answers: Sequence[dict[str, Any]]) -> list[Result]:
    return [
        Result(a["choice"], a["correct"], q["answer"], q["evidence"])
        for a, q in zip(answers, version.questions, strict=True)
    ]


async def _reading_ability(
    session: AsyncSession, user_id: uuid.UUID, level: CefrLevel, rules: Rules
) -> SkillEstimate:
    row = await session.scalar(
        select(SkillEstimate)
        .where(SkillEstimate.user_id == user_id, SkillEstimate.skill == SKILL)
        .with_for_update()
    )
    if row is None:
        # Like grammar: start from the anchor of the level the learner reads at.
        row = SkillEstimate(
            user_id=user_id, skill=SKILL, rating=rules.difficulty.cefr_anchor[level], attempts=0
        )
        session.add(row)
    return row


async def answer(
    session: AsyncSession,
    reading: ReadingSession,
    choices: Sequence[int],
    *,
    rules: Rules,
    now: datetime,
) -> list[Result]:
    """Grade the quiz; the first answers count, later ones get the stored results back.
    Raises `ReadingError` without a ready version with questions, or for answers that
    do not fit them; commits."""
    version = (
        await session.get(ArticleVersion, reading.version_id)
        if reading.version_id is not None
        else None
    )
    if version is None or version.status != "ready" or not version.questions:
        raise ReadingError("no_questions")
    if reading.answers is not None:
        return results(version, reading.answers)
    if len(choices) != len(version.questions) or any(
        not 0 <= c < len(q["options"]) for c, q in zip(choices, version.questions, strict=False)
    ):
        raise ReadingError("invalid_answers")
    answers = [
        {"choice": c, "correct": c == q["answer"]}
        for c, q in zip(choices, version.questions, strict=True)
    ]
    level = cast(CefrLevel, version.level)
    ability = await _reading_ability(session, reading.user_id, level, rules)
    difficulty = rules.difficulty.cefr_anchor[level]
    for a in answers:
        ability.rating = update_ability(
            ability.rating, difficulty, a["correct"], ability.attempts, rules, GUESS
        )
        ability.attempts += 1
    reading.answers = answers
    reading.finished_at = now
    await session.commit()
    return results(version, answers)


async def due_words(
    session: AsyncSession,
    user_id: uuid.UUID,
    paragraphs: Sequence[str],
    *,
    rules: Rules,
    now: datetime,
) -> list[dict[str, Any]]:
    """Words of the text the learner has due for review now, as the review queue counts
    them (Q43d): [{"word_id", "form"}], each word once, in order of first use."""
    seen = glossary.tokens(paragraphs)
    entries = await glossary.load_entries(session, (form for form, _ in seen))
    if not entries:
        return []
    ahead = now + timedelta(minutes=rules.vocab.learn_ahead_minutes)
    due = set(
        await session.scalars(
            select(UserCard.word_id).where(
                UserCard.user_id == user_id,
                UserCard.status == "learning",
                UserCard.due <= ahead,
                UserCard.word_id.in_({e.word_id for e in entries.values()}),
            )
        )
    )
    marked: list[dict[str, Any]] = []
    listed: set[int] = set()
    for form, _ in seen:
        entry = entries.get(form)
        if entry is not None and entry.word_id in due and entry.word_id not in listed:
            listed.add(entry.word_id)
            marked.append({"word_id": entry.word_id, "form": form})
    return marked
