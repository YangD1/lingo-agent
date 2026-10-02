"""What the learning engine suggests now (ADR 0016): the algorithm's candidates, no model.

The dashboard turns them into quick replies for the tutor conversation, or into links
when no chat model is set up.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.adaptive.kc.catalog import CefrLevel, get_grammar_catalog
from app.adaptive.rules import get_rules
from app.advice.candidates import Kind, candidates
from app.advice.reminder import Reason
from app.api.vocab import TimeZone
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.providers.config import resolve_route
from app.providers.errors import NoModelConfiguredError
from app.providers.llm import get_providers_config
from app.providers.tenant import load_provider_context
from app.services.vocab.scheduler import learner_zone

router = APIRouter(prefix="/advice", tags=["advice"])


class KcRef(BaseModel):
    id: str
    name_en: str
    name_zh: str
    cefr: CefrLevel


class BookRef(BaseModel):
    id: str
    name_en: str
    name_zh: str


class AdviceItemOut(BaseModel):
    candidate_id: str
    kind: Kind
    # Live evidence: due words, new words left, or mistakes.
    count: int | None
    # Placement: days since the latest finished test, None if never; a test is open.
    days_since: int | None
    in_progress: bool
    # Placement (task 50): why to take it now; the last test's level and that level's
    # grammar points learned out of all.
    reason: Reason | None
    level: CefrLevel | None
    learned: int | None
    total: int | None
    kc: KcRef | None
    p_mastery: float | None
    book: BookRef | None


class AdviceOut(BaseModel):
    # Best first.
    items: list[AdviceItemOut]
    # A chat model is set up, so the tutor can talk the advice over; otherwise the page
    # shows the items as links.
    model_ready: bool


@router.get("")
async def get_advice(
    user: CurrentUser, tenant: CurrentTenant, session: SessionDep, tz: TimeZone = None
) -> AdviceOut:
    found = await candidates(
        session,
        user.id,
        rules=get_rules(),
        catalog=get_grammar_catalog(),
        tz=await learner_zone(session, user.id, tz),
    )
    await session.commit()  # stale mastery rows may have been rebuilt
    try:
        resolve_route(
            get_providers_config(), await load_provider_context(session, tenant.id), "llm", "chat"
        )
        model_ready = True
    except NoModelConfiguredError:
        model_ready = False
    return AdviceOut(
        items=[
            AdviceItemOut(
                candidate_id=c.id,
                kind=c.kind,
                count=c.count,
                days_since=c.days_since,
                in_progress=c.in_progress,
                reason=c.reason,
                level=c.level,
                learned=c.learned,
                total=c.total,
                kc=KcRef(id=c.kc.id, name_en=c.kc.name_en, name_zh=c.kc.name_zh, cefr=c.kc.cefr)
                if c.kc
                else None,
                p_mastery=c.p_mastery,
                book=BookRef(id=c.book.id, name_en=c.book.name_en, name_zh=c.book.name_zh)
                if c.book
                else None,
            )
            for c in found
            # "Not now" (Q50d): the page doesn't offer it; the tutor still can if asked.
            if not c.snoozed
        ],
        model_ready=model_ready,
    )
