"""Grammar evidence from speaking conversations (ADR 0029 §4).

Reflection tags a speaking conversation's turns like any chat's, recorded with source
`speaking`. What it tags is a transcript, so less of it is kept: a spoken turn too
short to trust gives no mistakes (Q58a), and a turn whose transcript the learner fixed
and sent again gives nothing at all (Q58b): the fixed text, a turn of its own, counts.
"""

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.evidence import ChatEvidence
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import Rules, get_rules
from app.db.models import Attachment, KCEvidence, SpeakingSession
from app.writing.text import word_count

# Conversations whose turns are spoken practice.
SPEAKING_PURPOSES = frozenset({"speaking", "realtime"})


def evidence_source(purpose: str | None) -> str:
    return "speaking" if purpose in SPEAKING_PURPOSES else "chat"


async def spoken_message_ids(
    session: AsyncSession, conversation_id: uuid.UUID, message_ids: Sequence[str]
) -> set[str]:
    """Of `message_ids`, the learner messages sent as a recording."""
    if not message_ids:
        return set()
    rows = await session.scalars(
        select(Attachment.message_id).where(
            Attachment.conversation_id == conversation_id,
            Attachment.message_id.in_(message_ids),
            Attachment.kind == "audio",
        )
    )
    return {message_id for message_id in rows if message_id is not None}


async def kept_evidence(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    items: Sequence[ChatEvidence],
    texts: Mapping[str, str],
    rules: Rules,
) -> list[ChatEvidence]:
    """The items worth recording; `texts` are the learner messages' text by id."""
    corrected = set(
        await session.scalar(
            select(SpeakingSession.corrected_message_ids).where(
                SpeakingSession.conversation_id == conversation_id
            )
        )
        or ()
    )
    spoken = await spoken_message_ids(session, conversation_id, list(texts))
    too_short = {
        message_id
        for message_id in spoken
        if word_count(texts.get(message_id, "")) < rules.speaking.min_words_for_mistakes
    }
    return [
        item
        for item in items
        if item.message_id not in corrected
        and not (not item.correct and item.message_id in too_short)
    ]


async def mark_corrected(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, message_id: str
) -> bool:
    """The learner fixed this turn's transcript and sends it again (Q58b): the turn
    gives no evidence from now on, and what it gave is taken back. False when the
    conversation has no speaking session. Does not commit."""
    row = await session.scalar(
        select(SpeakingSession)
        .where(
            SpeakingSession.conversation_id == conversation_id,
            SpeakingSession.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        return False
    if message_id not in row.corrected_message_ids:
        row.corrected_message_ids = [*row.corrected_message_ids, message_id]
    rules, catalog = get_rules(), get_grammar_catalog()
    await mastery.ensure_current(session, user_id, rules=rules, catalog=catalog)
    removed = await session.scalars(
        delete(KCEvidence)
        .where(KCEvidence.user_id == user_id, KCEvidence.message_id == message_id)
        .returning(KCEvidence.kc_id)
    )
    affected = set(removed)
    if affected:
        await mastery.refresh(session, user_id, affected, rules=rules, catalog=catalog)
    await session.flush()
    return True
