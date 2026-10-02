"""Reviewing a piece of writing (P2 plan §4.2, ADR 0023 §5).

`/writing` and writing_coach both `create` a pending submission and `review` it: one
`writing_review` call, checked in code (`review.check`); the mistakes kept become
`kc_evidence` rows (source `writing`, production) that point back to the submission,
mastery is replayed from them (a learned KC takes an Again, ADR 0021 §7), and the
words the learner did not know go on their list as reflection's do. Scores are stored
for the learner to see and never feed mastery.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive import mastery
from app.adaptive.exercise.inputs import ExplainIn
from app.adaptive.kc.catalog import GrammarCatalog, get_grammar_catalog
from app.adaptive.rules import Rules, get_rules
from app.agents.exercise_graph import StructuredCall
from app.db.models import KCEvidence, UserProfile, WritingSubmission
from app.services.vocab import mine
from app.writing import review as writing_review
from app.writing.review import Checked, Review
from app.writing.text import length_error, sentences, word_count

logger = logging.getLogger(__name__)


class LengthError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def create(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    text: str,
    prompt: str = "",
    conversation_id: uuid.UUID | None = None,
) -> WritingSubmission:
    """A pending submission; does not commit. Raises `LengthError` for a text too
    short or too long to review (Q38f), before any model is called."""
    text = text.strip()
    if (code := length_error(text)) is not None:
        raise LengthError(code)
    row = WritingSubmission(
        user_id=user_id,
        conversation_id=conversation_id,
        prompt=prompt.strip(),
        text=text,
        word_count=word_count(text),
        status="pending",
    )
    session.add(row)
    await session.flush()
    return row


@dataclass(frozen=True, slots=True)
class _Learner:
    level: str
    explain_in: ExplainIn


async def _learner(session: AsyncSession, user_id: uuid.UUID, rules: Rules) -> _Learner:
    profile = await session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    return _Learner(
        level=(profile.cefr_level if profile else None) or rules.practice.default_level,
        explain_in="en" if profile and profile.explanation_language == "en" else "zh",
    )


async def review(
    maker: async_sessionmaker[AsyncSession], submission_id: int, call: StructuredCall
) -> None:
    """Review a pending submission and save the result; commits. Raises when the model
    call fails, leaving the submission pending for the caller to `fail`."""
    rules, catalog = get_rules(), get_grammar_catalog()
    async with maker() as session:
        row = await session.get(WritingSubmission, submission_id)
        if row is None or row.status != "pending":
            return  # deleted meanwhile, or already reviewed
        learner = await _learner(session, row.user_id, rules)
        parts = sentences(row.text)
        messages = writing_review.review_messages(
            row.prompt, parts, learner.level, learner.explain_in
        )
    reply = await call(messages, Review)
    checked = writing_review.check(cast(Review, reply.output), parts, catalog)
    if checked.dropped:
        logger.info("writing review %s: dropped %d mistakes", submission_id, checked.dropped)
    async with maker() as session:
        row = await session.get(WritingSubmission, submission_id, with_for_update=True)
        if row is None or row.status != "pending":
            return
        await save(session, row, checked, reply.model, rules=rules, catalog=catalog)
        user_id = row.user_id
        await session.commit()
    # Best effort, like reflection's: the review matters more than the word list.
    try:
        async with maker() as session:
            words = await collect_words(session, user_id, checked.vocab)
            await session.execute(
                update(WritingSubmission)
                .where(WritingSubmission.id == submission_id)
                .values(words=words)
            )
            await session.commit()
    except Exception:
        logger.exception("collecting words failed for writing %s", submission_id)


async def save(
    session: AsyncSession,
    row: WritingSubmission,
    checked: Checked,
    model: str | None,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
) -> None:
    """Store the review, its evidence and the mastery it changes; does not commit.

    Evidence from an earlier review of the same submission is replaced, so a retry
    leaves one set of rows.
    """
    await mastery.ensure_current(session, row.user_id, rules=rules, catalog=catalog)
    removed = await session.scalars(
        delete(KCEvidence).where(KCEvidence.writing_id == row.id).returning(KCEvidence.kc_id)
    )
    affected = set(removed)
    for sentence in checked.corrections:
        for m in cast(list[dict[str, str]], sentence["mistakes"]):
            session.add(
                KCEvidence(
                    user_id=row.user_id,
                    kc_id=m["kc_id"],
                    correct=False,
                    evidence="production",
                    source="writing",
                    conversation_id=row.conversation_id,
                    writing_id=row.id,
                    error_type=m["error_type"],
                    severity=m["severity"],
                    original=m["original"],
                    correction=m["correction"],
                )
            )
            affected.add(m["kc_id"])
    await session.flush()
    await mastery.refresh(session, row.user_id, affected, rules=rules, catalog=catalog)
    row.status = "done"
    row.corrections = checked.corrections
    row.scores = checked.scores
    row.summary = checked.summary
    row.model = model
    row.error_code = None
    row.reviewed_at = datetime.now(UTC)


async def collect_words(
    session: AsyncSession, user_id: uuid.UUID, candidates: list[str]
) -> list[dict[str, object]]:
    """Put the words the dictionary knows on the learner's list; commits. "went" and
    "go" are one word, listed once."""
    found = [match.word for text in candidates if (match := await mine.lookup(session, text))]
    collected = await mine.collect(session, user_id, found)
    return [{"word_id": c.word.id, "word": c.word.word, "added": c.added} for c in collected]


async def fail(maker: async_sessionmaker[AsyncSession], submission_id: int, code: str) -> None:
    async with maker() as session:
        await session.execute(
            update(WritingSubmission)
            .where(WritingSubmission.id == submission_id, WritingSubmission.status == "pending")
            .values(status="failed", error_code=code)
        )
        await session.commit()
