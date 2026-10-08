"""The tutor's diagnosis as the learner sees it on the learner model page (task 47).

Shows the latest diagnosis that found something (Q47a), with the mistakes it cites that
still exist (Q47d: a deleted citation is counted, nothing is re-checked), and deletes a
diagnosis the learner disagrees with (Q47c).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.kc.catalog import GrammarCatalog, GrammarKC
from app.adaptive.rules import Rules
from app.db.models import Conversation, Diagnosis, KCEvidence, KCMastery, Memory


@dataclass(frozen=True, slots=True)
class CitedMistake:
    row: KCEvidence
    # None once the conversation is deleted.
    conversation_title: str | None


@dataclass(frozen=True, slots=True)
class NamedKC:
    kc: GrammarKC
    learned: bool


@dataclass(frozen=True, slots=True)
class CauseView:
    hypothesis: str
    # Root first; KCs gone from the catalog are left out.
    kcs: list[NamedKC]
    confidence: str
    suggestion: str
    # The cited mistakes still stored, in the order cited.
    evidence: list[CitedMistake]
    cited: int


@dataclass(frozen=True, slots=True)
class DiagnosisView:
    id: uuid.UUID
    created_at: datetime
    language: str
    causes: list[CauseView]
    # Whether its practice boost still applies (Q46e): within `boost_days`.
    boost_until: datetime
    boost_active: bool


@dataclass(frozen=True, slots=True)
class Latest:
    # The newest diagnosis with causes; None when none found any.
    diagnosis: DiagnosisView | None
    # When the tutor last looked, found something or not.
    checked_at: datetime | None


async def latest(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime,
) -> Latest:
    """May rebuild stale mastery rows first (for "learned"); the caller commits."""
    checked_at = await session.scalar(
        select(Diagnosis.created_at)
        .where(Diagnosis.user_id == user_id)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    row = await session.scalar(
        select(Diagnosis)
        .where(Diagnosis.user_id == user_id, func.jsonb_array_length(Diagnosis.root_causes) > 0)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    if row is None:
        return Latest(diagnosis=None, checked_at=checked_at)

    await mastery.ensure_current(session, user_id, rules=rules, catalog=catalog)
    kc_ids = {kc_id for cause in row.root_causes for kc_id in cause["kc_ids"]}
    learned = set(
        await session.scalars(
            select(KCMastery.kc_id).where(
                KCMastery.user_id == user_id,
                KCMastery.kind == "grammar",
                KCMastery.kc_id.in_(kc_ids),
                KCMastery.mastered_at.is_not(None),
            )
        )
    )
    evidence_ids = {i for cause in row.root_causes for i in cause["evidence_ids"]}
    mistakes = {
        e.id: e
        for e in await session.scalars(
            select(KCEvidence).where(KCEvidence.user_id == user_id, KCEvidence.id.in_(evidence_ids))
        )
    }
    titles = await _titles(session, user_id, {e.conversation_id for e in mistakes.values()})
    causes = [
        CauseView(
            hypothesis=cause["hypothesis"],
            kcs=[
                NamedKC(kc, kc.id in learned)
                for kc_id in cause["kc_ids"]
                if (kc := catalog.get(kc_id)) is not None
            ],
            confidence=cause["confidence"],
            suggestion=cause["suggestion"],
            evidence=[
                CitedMistake(e, titles.get(e.conversation_id) if e.conversation_id else None)
                for i in cause["evidence_ids"]
                if (e := mistakes.get(i)) is not None
            ],
            cited=len(cause["evidence_ids"]),
        )
        for cause in row.root_causes
    ]
    boost_until = row.created_at + timedelta(days=rules.diagnosis.boost_days)
    return Latest(
        diagnosis=DiagnosisView(
            id=row.id,
            created_at=row.created_at,
            language=row.language,
            causes=causes,
            boost_until=boost_until,
            boost_active=now < boost_until,
        ),
        checked_at=checked_at,
    )


async def _titles(
    session: AsyncSession, user_id: uuid.UUID, ids: set[uuid.UUID | None]
) -> dict[uuid.UUID, str | None]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await session.execute(
        select(Conversation.id, Conversation.title).where(
            Conversation.user_id == user_id, Conversation.id.in_(wanted)
        )
    )
    return {i: title for i, title in rows.all()}


class DiagnosisNotFoundError(Exception):
    pass


async def delete_diagnosis(
    session: AsyncSession, user_id: uuid.UUID, diagnosis_id: uuid.UUID
) -> None:
    """Delete a diagnosis the learner disagrees with (Q47c), which ends its boost, and
    the memory it wrote unless a later diagnosis has rewritten that memory; commits."""
    row = await session.scalar(
        select(Diagnosis).where(Diagnosis.id == diagnosis_id, Diagnosis.user_id == user_id)
    )
    if row is None:
        raise DiagnosisNotFoundError(diagnosis_id)
    memory_id = row.memory_id
    if memory_id is not None:
        # Diagnoses update one memory in place (Q46d): it says what the newest one found.
        newest = await session.scalar(
            select(Diagnosis.id)
            .where(Diagnosis.user_id == user_id, Diagnosis.memory_id == memory_id)
            .order_by(Diagnosis.created_at.desc())
            .limit(1)
        )
        if newest == row.id:
            await session.execute(
                delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
            )
    await session.delete(row)
    await session.commit()
