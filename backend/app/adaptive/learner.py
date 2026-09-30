"""The learner model as the learner sees it: read it, and delete it (ADR 0010, P1 plan §7).

Only grammar KCs with evidence are listed; words take their mastery from FSRS and are
shown on the vocabulary pages. Deleting is real deletion, and takes with it the
`grammar_tagging` activity that quotes the deleted mistakes (ADR 0013 §3).
"""

import uuid
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any, Literal

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity import service as activity
from app.adaptive import mastery
from app.adaptive.bkt import counted
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog, GrammarKC
from app.adaptive.placement.grammar_test import cefr_for
from app.adaptive.placement.writeback import latest_result
from app.adaptive.rules import Rules
from app.db.models import Conversation, KCEvidence, KCMastery, SkillEstimate

type MasteryState = Literal["mastered", "learning", "weak"]

# Evidence shown per KC; a KC collects a few per conversation at most.
EVIDENCE_LIMIT = 100


class EvidenceNotFoundError(Exception):
    pass


def mastery_state(p_mastery: float, rules: Rules) -> MasteryState:
    if p_mastery >= rules.bkt.mastered:
        return "mastered"
    return "weak" if p_mastery < rules.bkt.weak else "learning"


@dataclass(frozen=True, slots=True)
class KCStatus:
    kc: GrammarKC
    mastery: KCMastery
    state: MasteryState
    # All stored mistakes, counted by BKT or not.
    mistakes: int


@dataclass(frozen=True, slots=True)
class Skill:
    """A skill estimate with what makes its rating readable.

    Grammar gets the level its ability maps to. Vocabulary's rating is ln V (the rank
    at which the learner knows half the words), not a size, so it gets the estimated
    size and reference level of the latest finished placement test, the only writer
    of skill estimates for now.
    """

    skill: str
    rating: float
    attempts: int
    cefr: CefrLevel | None = None
    vocab_size: int | None = None
    # False when the vocabulary test counted many pseudo-words as known.
    reliable: bool | None = None


@dataclass(frozen=True, slots=True)
class Overview:
    # Weakest first.
    kcs: list[KCStatus]
    # Catalog size per level, to show how many are not met yet.
    totals: dict[CefrLevel, int]
    skills: list[Skill]


async def overview(
    session: AsyncSession, user_id: uuid.UUID, *, rules: Rules, catalog: GrammarCatalog
) -> Overview:
    """May rebuild stale mastery rows first; the caller commits."""
    await mastery.ensure_current(session, user_id, rules=rules, catalog=catalog)
    rows = (
        await session.scalars(
            select(KCMastery).where(KCMastery.user_id == user_id, KCMastery.kind == "grammar")
        )
    ).all()
    counts = await session.execute(
        select(KCEvidence.kc_id, func.count())
        .where(KCEvidence.user_id == user_id, KCEvidence.correct.is_(False))
        .group_by(KCEvidence.kc_id)
    )
    mistakes: dict[str, int] = {kc_id: n for kc_id, n in counts.all()}
    kcs = [
        KCStatus(
            kc=kc,
            mastery=row,
            state=mastery_state(row.p_mastery, rules),
            mistakes=mistakes.get(row.kc_id, 0),
        )
        for row in rows
        if (kc := catalog.get(row.kc_id)) is not None
    ]
    kcs.sort(key=lambda s: (s.mastery.p_mastery, -s.mastery.observations, s.kc.id))
    estimates = await session.scalars(
        select(SkillEstimate).where(SkillEstimate.user_id == user_id).order_by(SkillEstimate.skill)
    )
    placement = await latest_result(session, user_id)
    return Overview(
        kcs=kcs,
        totals=dict(Counter(kc.cefr for kc in catalog.kcs)),
        skills=[_skill(row, placement, rules) for row in estimates],
    )


def _skill(row: SkillEstimate, placement: dict[str, Any] | None, rules: Rules) -> Skill:
    skill = Skill(row.skill, row.rating, row.attempts)
    if row.skill == "grammar":
        return replace(skill, cefr=cefr_for(row.rating, rules))
    vocab = placement.get("vocab") if placement else None
    if row.skill == "vocab" and isinstance(vocab, dict):
        return replace(
            skill,
            cefr=vocab.get("reference_cefr"),
            vocab_size=vocab.get("size"),
            reliable=vocab.get("reliable"),
        )
    return skill


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    row: KCEvidence
    # Whether BKT used it: low-severity slips and repeats within a turn are not used.
    counted: bool
    # None once the conversation is deleted.
    conversation_title: str | None


async def kc_evidence(
    session: AsyncSession, user_id: uuid.UUID, kc_id: str, *, rules: Rules
) -> tuple[list[EvidenceItem], int]:
    """A KC's evidence, newest first, at most EVIDENCE_LIMIT, and the total count."""
    rows = list(
        await session.scalars(
            select(KCEvidence)
            .where(KCEvidence.user_id == user_id, KCEvidence.kc_id == kc_id)
            .order_by(KCEvidence.created_at, KCEvidence.id)
        )
    )
    # "Counted" needs the whole history: the per-turn cap looks at neighbours.
    observations = [mastery.observation(row) for row in rows]
    used = {id(o) for o in counted(observations, rules)}
    shown = list(zip(rows, observations, strict=True))[::-1][:EVIDENCE_LIMIT]
    conversation_ids = {row.conversation_id for row, _ in shown if row.conversation_id}
    titles: dict[uuid.UUID, str | None] = {}
    if conversation_ids:
        titles = dict(
            (
                await session.execute(
                    select(Conversation.id, Conversation.title).where(
                        Conversation.user_id == user_id, Conversation.id.in_(conversation_ids)
                    )
                )
            ).all()
        )
    return [
        EvidenceItem(
            row=row,
            counted=id(obs) in used,
            conversation_title=titles.get(row.conversation_id) if row.conversation_id else None,
        )
        for row, obs in shown
    ], len(rows)


async def delete_evidence(
    session: AsyncSession,
    user_id: uuid.UUID,
    evidence_id: int,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
) -> None:
    """Delete one piece of evidence (say, a mistake the tagger got wrong), recompute
    its KC and drop it from the turn's activity; commits."""
    row = await session.scalar(
        select(KCEvidence).where(KCEvidence.id == evidence_id, KCEvidence.user_id == user_id)
    )
    if row is None:
        raise EvidenceNotFoundError(evidence_id)
    kc_id, correct, original, message_id = row.kc_id, row.correct, row.original, row.message_id
    await session.delete(row)
    await session.flush()
    await mastery.refresh(session, user_id, [kc_id], rules=rules, catalog=catalog)
    if message_id is not None:
        await activity.untag(
            session,
            user_id=user_id,
            turn_id=message_id,
            kc_id=kc_id,
            correct=correct,
            original=original,
        )
    await session.commit()


async def delete_all(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Delete the learner's evidence, mastery, skill estimates and grammar tags;
    commits. Returns the number of evidence rows deleted."""
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        delete(KCEvidence).where(KCEvidence.user_id == user_id)
    )
    await session.execute(delete(KCMastery).where(KCMastery.user_id == user_id))
    await session.execute(delete(SkillEstimate).where(SkillEstimate.user_id == user_id))
    await activity.forget_grammar_tags(session, user_id)
    await session.commit()
    return result.rowcount
