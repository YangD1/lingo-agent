"""Today's plan (ADR 0027): read it (drafted on first read), confirm it with or without
adjustments, decline or undo it. The tutor's proposals are cards (api/cards.py)."""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.adaptive.daily_plan import service
from app.adaptive.daily_plan.algorithm import ItemKind, PlanChoice, budget
from app.adaptive.daily_plan.service import PlanStateError, PlanView
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.api.errors import api_error
from app.api.vocab import TimeZone
from app.db.models import Article, DailyPlan
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.services.vocab.scheduler import learner_zone

router = APIRouter(prefix="/plan", tags=["plan"])

BodyTimeZone = Annotated[str | None, Field(max_length=64)]


class ChoiceIn(BaseModel):
    review: int = Field(ge=0)
    new_words: int = Field(ge=0)
    practice: bool
    reading: bool
    writing: bool
    # Plans and cards from before speaking was an item have none.
    speaking: bool = False


class ChoiceOut(ChoiceIn):
    pass


class NamedKC(BaseModel):
    id: str
    name_en: str
    name_zh: str


class NamedArticle(BaseModel):
    id: int
    title: str


class ItemOut(BaseModel):
    kind: ItemKind
    minutes: float
    count: int | None
    done: int
    target: int
    complete: bool
    kc: NamedKC | None = None
    article: NamedArticle | None = None


class LimitsOut(BaseModel):
    """What the plan may be adjusted to (Q48c)."""

    reviews_due: int
    new_left: int
    practice: bool
    reading: bool
    max_count: int
    # Minutes of speaking that complete the speaking item (Q59d).
    speaking_minutes: int


class PlanOut(BaseModel):
    id: uuid.UUID
    day: date
    status: str
    # The tutor's card this plan came from; undoing it goes through that card.
    card_id: uuid.UUID | None
    choice: ChoiceOut
    items: list[ItemOut]
    minutes: float
    # The learner's daily minutes, or the default when they set none.
    budget: int
    budget_set: bool
    limits: LimitsOut
    # Estimated minutes per review / new word / set / article / text, for live totals.
    estimates: dict[ItemKind, float]


class ConfirmIn(BaseModel):
    choice: ChoiceIn | None = None
    tz: BodyTimeZone = None


class DecideIn(BaseModel):
    tz: BodyTimeZone = None


async def _out(session: SessionDep, view: PlanView) -> PlanOut:
    rules, catalog = get_rules(), get_grammar_catalog()
    inputs, plan = view.inputs, view.plan
    title = None
    if inputs.article_id is not None:
        title = await session.scalar(select(Article.title).where(Article.id == inputs.article_id))
    items: list[ItemOut] = []
    for p in view.progress:
        item = ItemOut(
            kind=p.item.kind,
            minutes=p.item.minutes,
            count=p.item.count,
            done=p.done,
            target=p.target,
            complete=p.complete,
        )
        if p.item.kind == "practice" and (kc := catalog.get(str(p.item.ref))):
            item.kc = NamedKC(id=kc.id, name_en=kc.name_en, name_zh=kc.name_zh)
        if p.item.kind == "reading" and inputs.article_id is not None and title is not None:
            item.article = NamedArticle(id=inputs.article_id, title=title)
        items.append(item)
    per = rules.daily_plan.minutes
    return PlanOut(
        id=plan.id,
        day=plan.day,
        status=plan.status,
        card_id=plan.card_id,
        choice=ChoiceOut.model_validate(plan.choice),
        items=items,
        minutes=view.minutes,
        budget=budget(inputs, rules),
        budget_set=inputs.minutes is not None,
        limits=LimitsOut(
            reviews_due=inputs.reviews_due,
            new_left=inputs.new_left,
            practice=inputs.practice_kc is not None,
            reading=inputs.article_id is not None,
            max_count=rules.daily_plan.max_count,
            speaking_minutes=rules.daily_plan.speaking_target_minutes,
        ),
        estimates={
            "review": per.review,
            "new_words": per.new_word,
            "practice": per.practice,
            "reading": per.reading,
            "writing": per.writing,
            "speaking": per.speaking,
        },
    )


@router.get("/today")
async def get_today(
    user: CurrentUser, tenant: CurrentTenant, session: SessionDep, tz: TimeZone = None
) -> PlanOut:
    """Today's plan in the learner's zone, drafted on the first read of the day."""
    rules = get_rules()
    zone = await learner_zone(session, user.id, tz)
    plan = await service.today(session, user.id, tenant.id, rules=rules, tz=zone)
    out = await _out(session, await service.view(session, plan, rules=rules, tz=zone))
    await session.commit()  # stale mastery rows may have been rebuilt
    return out


_CONFLICTS: dict[int | str, dict[str, Any]] = {
    404: {"description": "plan_not_found"},
    409: {"description": "plan_not_pending, plan_not_applied, plan_from_card or plan_expired"},
}


async def _decided(session: SessionDep, plan: DailyPlan, zone_name: str | None) -> PlanOut:
    zone = await learner_zone(session, plan.user_id, zone_name)
    return await _out(session, await service.view(session, plan, rules=get_rules(), tz=zone))


def _error(exc: PlanStateError) -> Exception:
    code = status.HTTP_404_NOT_FOUND if exc.code == "plan_not_found" else status.HTTP_409_CONFLICT
    return api_error(code, exc.code, exc.message)


@router.post("/{plan_id}/confirm", responses=_CONFLICTS)
async def confirm(
    plan_id: uuid.UUID, body: ConfirmIn, user: CurrentUser, session: SessionDep
) -> PlanOut:
    """Confirm the plan, adjusted to `choice` if given (kept within today's limits)."""
    zone = await learner_zone(session, user.id, body.tz)
    choice = PlanChoice(**body.choice.model_dump()) if body.choice else None
    try:
        plan = await service.confirm(
            session, user.id, plan_id, rules=get_rules(), tz=zone, choice=choice
        )
    except PlanStateError as exc:
        raise _error(exc) from exc
    return await _decided(session, plan, body.tz)


@router.post("/{plan_id}/decline", responses=_CONFLICTS)
async def decline(
    plan_id: uuid.UUID, body: DecideIn, user: CurrentUser, session: SessionDep
) -> PlanOut:
    """No plan today (Q48f); the tutor can still propose one."""
    zone = await learner_zone(session, user.id, body.tz)
    try:
        plan = await service.decline(session, user.id, plan_id, tz=zone)
    except PlanStateError as exc:
        raise _error(exc) from exc
    return await _decided(session, plan, body.tz)


@router.post("/{plan_id}/undo", responses=_CONFLICTS)
async def undo(
    plan_id: uuid.UUID, body: DecideIn, user: CurrentUser, session: SessionDep
) -> PlanOut:
    """A confirmed plan goes back to waiting for confirmation. A plan from a tutor's card
    is undone through the card (`POST /cards/{id}/undo`), which restores the plan before."""
    zone = await learner_zone(session, user.id, body.tz)
    try:
        plan = await service.undo(session, user.id, plan_id, tz=zone)
    except PlanStateError as exc:
        raise _error(exc) from exc
    return await _decided(session, plan, body.tz)
