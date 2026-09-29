"""The learner model page: grammar mastery with its evidence, skill estimates, and
deleting them (ADR 0010, P1 plan §7). Everything here is the current user's own data."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.adaptive import learner
from app.adaptive.kc.catalog import CefrLevel, get_grammar_catalog
from app.adaptive.learner import MasteryState
from app.adaptive.rules import get_rules
from app.api.errors import api_error
from app.deps import CurrentUser, SessionDep

router = APIRouter(prefix="/learner", tags=["learner"])


class KCOut(BaseModel):
    kc_id: str
    name_en: str
    name_zh: str
    cefr: CefrLevel
    p_mastery: float
    state: MasteryState
    # Observations BKT used, and the correct ones among them by kind.
    observations: int
    recog_correct: int
    produce_correct: int
    # Every stored mistake, including ones BKT left out.
    mistakes: int
    last_evidence_at: datetime | None


class LevelOut(BaseModel):
    total: int
    seen: int


class SkillOut(BaseModel):
    skill: str
    rating: float
    attempts: int


class Thresholds(BaseModel):
    mastered: float
    weak: float


class LearnerOut(BaseModel):
    kcs: list[KCOut]
    levels: dict[CefrLevel, LevelOut]
    skills: list[SkillOut]
    thresholds: Thresholds


class EvidenceOut(BaseModel):
    id: int
    correct: bool
    evidence: str
    source: str
    error_type: str | None
    severity: str | None
    original: str | None
    correction: str | None
    l1_transfer: bool
    counted: bool
    conversation_id: uuid.UUID | None
    conversation_title: str | None
    created_at: datetime


class EvidencePage(BaseModel):
    evidence: list[EvidenceOut]
    # All evidence of the KC; `evidence` holds the newest of it.
    total: int


class Deleted(BaseModel):
    deleted: int


@router.get("")
async def get_learner(user: CurrentUser, session: SessionDep) -> LearnerOut:
    rules = get_rules()
    overview = await learner.overview(session, user.id, rules=rules, catalog=get_grammar_catalog())
    await session.commit()  # stale rows may have been rebuilt
    seen: dict[CefrLevel, int] = {}
    for s in overview.kcs:
        seen[s.kc.cefr] = seen.get(s.kc.cefr, 0) + 1
    return LearnerOut(
        kcs=[
            KCOut(
                kc_id=s.kc.id,
                name_en=s.kc.name_en,
                name_zh=s.kc.name_zh,
                cefr=s.kc.cefr,
                p_mastery=s.mastery.p_mastery,
                state=s.state,
                observations=s.mastery.observations,
                recog_correct=s.mastery.recog_correct,
                produce_correct=s.mastery.produce_correct,
                mistakes=s.mistakes,
                last_evidence_at=s.mastery.last_evidence_at,
            )
            for s in overview.kcs
        ],
        levels={
            level: LevelOut(total=total, seen=seen.get(level, 0))
            for level, total in overview.totals.items()
        },
        skills=[
            SkillOut(skill=s.skill, rating=s.rating, attempts=s.attempts) for s in overview.skills
        ],
        thresholds=Thresholds(mastered=rules.bkt.mastered, weak=rules.bkt.weak),
    )


@router.get("/kcs/{kc_id}/evidence")
async def get_evidence(kc_id: str, user: CurrentUser, session: SessionDep) -> EvidencePage:
    if kc_id not in get_grammar_catalog():
        raise api_error(status.HTTP_404_NOT_FOUND, "kc_not_found", "unknown grammar point")
    items, total = await learner.kc_evidence(session, user.id, kc_id, rules=get_rules())
    return EvidencePage(
        evidence=[
            EvidenceOut(
                id=i.row.id,
                correct=i.row.correct,
                evidence=i.row.evidence,
                source=i.row.source,
                error_type=i.row.error_type,
                severity=i.row.severity,
                original=i.row.original,
                correction=i.row.correction,
                l1_transfer=i.row.l1_transfer,
                counted=i.counted,
                conversation_id=i.row.conversation_id,
                conversation_title=i.conversation_title,
                created_at=i.row.created_at,
            )
            for i in items
        ],
        total=total,
    )


@router.delete("/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evidence(evidence_id: int, user: CurrentUser, session: SessionDep) -> Response:
    try:
        await learner.delete_evidence(
            session, user.id, evidence_id, rules=get_rules(), catalog=get_grammar_catalog()
        )
    except learner.EvidenceNotFoundError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "evidence_not_found", "evidence not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("")
async def delete_learner(user: CurrentUser, session: SessionDep) -> Deleted:
    """Delete all learning records. Really deleted."""
    return Deleted(deleted=await learner.delete_all(session, user.id))
