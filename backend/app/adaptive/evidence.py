"""Writing learner evidence to kc_evidence (ADR 0012 §2)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import ErrorType
from app.adaptive.rules import Severity
from app.db.models import KCEvidence

# Evidence from the learner's own turns in a conversation, typed or spoken (ADR 0029 §4):
# their mistakes are sentences they made up, unlike a test's or an exercise's.
CONVERSATION_SOURCES = ("chat", "speaking")


@dataclass(frozen=True, slots=True)
class ChatEvidence:
    """One observation from a learner's chat message, already validated."""

    message_id: str
    kc_id: str
    correct: bool
    error_type: ErrorType | None = None
    severity: Severity | None = None
    original: str | None = None
    correction: str | None = None
    l1_transfer: bool = False


async def record_chat_evidence(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_ids: Sequence[str],
    items: Sequence[ChatEvidence],
    source: str = "chat",
) -> set[str]:
    """Replace the evidence of these learner messages with `items`, recorded under
    `source` (a conversation source); does not commit.

    Replacing rather than appending makes a repeated reflection over the same messages
    (a retry, or a restart before the cursor moved) leave one set of rows, not two.
    Returns every KC whose evidence changed, including KCs that lost rows.
    """
    affected: set[str] = set()
    if message_ids:
        removed = await session.scalars(
            delete(KCEvidence)
            .where(
                KCEvidence.user_id == user_id,
                KCEvidence.source.in_(CONVERSATION_SOURCES),
                KCEvidence.message_id.in_(message_ids),
            )
            .returning(KCEvidence.kc_id)
        )
        affected.update(removed)
    for item in items:
        session.add(
            KCEvidence(
                user_id=user_id,
                kc_id=item.kc_id,
                correct=item.correct,
                evidence="production",
                source=source,
                conversation_id=conversation_id,
                message_id=item.message_id,
                error_type=item.error_type,
                severity=item.severity,
                original=item.original,
                correction=item.correction,
                l1_transfer=item.l1_transfer,
            )
        )
        affected.add(item.kc_id)
    await session.flush()
    return affected
