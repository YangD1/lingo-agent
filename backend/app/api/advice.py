"""Study advice on the dashboard (P1 plan §7.5.2): read the cache, refresh in the background."""

import math
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel

from app.adaptive.kc.catalog import CefrLevel, get_grammar_catalog
from app.adaptive.rules import get_rules
from app.advice import service
from app.advice.candidates import Kind
from app.advice.service import AdviceRefresher
from app.api.errors import api_error
from app.api.vocab import TimeZone
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.memory.reflection import LOCALE_COOKIE
from app.services.vocab.scheduler import learner_zone

router = APIRouter(prefix="/advice", tags=["advice"])

# The UI's locale; the cookie is only set once the learner picks a language by hand.
UiLocale = Annotated[str | None, Query(max_length=10)]


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
    # None: template advice, written by the page in the learner's language.
    title: str | None
    reason: str | None
    # Live evidence, shown next to the text: due words, new words left, or mistakes.
    count: int | None
    # Placement: days since the latest finished test, None if never; a test is open.
    days_since: int | None
    in_progress: bool
    kc: KcRef | None
    p_mastery: float | None
    book: BookRef | None


class AdviceOut(BaseModel):
    items: list[AdviceItemOut]
    # ai / no_model / failed / empty; None before the first generation.
    status: str | None
    generated_at: datetime | None
    # New advice is being written; the page may ask again shortly.
    refreshing: bool
    # When "refresh" is allowed again; None = now.
    refresh_after: datetime | None


def _refresher(request: Request) -> AdviceRefresher:
    refresher: AdviceRefresher = request.app.state.advice_refresher
    return refresher


async def _advice(
    request: Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    tz: str | None,
    locale: str | None,
    *,
    by_hand: bool = False,
) -> AdviceOut:
    zone = await learner_zone(session, user.id, tz)
    ui = service.advice_locale(locale or request.cookies.get(LOCALE_COOKIE))
    advice = await service.read(
        session, user.id, rules=get_rules(), catalog=get_grammar_catalog(), tz=zone, locale=ui
    )
    await session.commit()  # stale mastery rows may have been rebuilt
    refresher = _refresher(request)
    if by_hand:
        if advice.by_hand_after is not None:
            wait = math.ceil((advice.by_hand_after - datetime.now(UTC)).total_seconds())
            raise api_error(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "advice_refresh_limited",
                "advice can be refreshed once an hour",
                headers={"Retry-After": str(max(1, wait))},
            )
        refresher.schedule(user.id, tenant.id, tz=zone, locale=ui, by_hand=True)
    elif advice.stale:
        refresher.schedule(user.id, tenant.id, tz=zone, locale=ui)
    return AdviceOut(
        items=[
            AdviceItemOut(
                candidate_id=item.candidate_id,
                kind=c.kind,
                title=item.title,
                reason=item.reason,
                count=c.count,
                days_since=c.days_since,
                in_progress=c.in_progress,
                kc=KcRef(id=c.kc.id, name_en=c.kc.name_en, name_zh=c.kc.name_zh, cefr=c.kc.cefr)
                if c.kc
                else None,
                p_mastery=c.p_mastery,
                book=BookRef(id=c.book.id, name_en=c.book.name_en, name_zh=c.book.name_zh)
                if c.book
                else None,
            )
            for item, c in advice.items
        ],
        status=advice.status,
        generated_at=advice.generated_at,
        refreshing=refresher.is_busy(user.id),
        refresh_after=advice.by_hand_after,
    )


@router.get("")
async def get_advice(
    request: Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    tz: TimeZone = None,
    locale: UiLocale = None,
) -> AdviceOut:
    """The cached advice; regenerates it in the background when stale."""
    return await _advice(request, user, tenant, session, tz, locale)


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_advice(
    request: Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    tz: TimeZone = None,
    locale: UiLocale = None,
) -> AdviceOut:
    """Regenerate now, at most once an hour; returns the current advice meanwhile."""
    return await _advice(request, user, tenant, session, tz, locale, by_hand=True)
