"""Tutor cards (ADR 0015 §4): list a conversation's cards; apply, decline or undo one."""

import uuid
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.advice.candidates import Signals, signals
from app.api.errors import api_error
from app.api.vocab import TimeZone
from app.cards import service
from app.cards.service import CardNotFoundError, CardStateError
from app.chat.service import ConversationNotFoundError, get_owned_conversation
from app.db.models import TutorCard
from app.deps import CurrentUser, SessionDep
from app.services.vocab.scheduler import learner_zone

router = APIRouter(tags=["cards"])


class CardOut(BaseModel):
    id: uuid.UUID
    turn_id: str
    kind: str
    params: dict[str, Any]
    status: str
    # Names resolved from the catalogs (book, grammar point).
    display: dict[str, Any]
    # Link cards: current numbers for the page they lead to; None elsewhere.
    live: dict[str, Any] | None = None
    created_at: str | None
    decided_at: str | None
    undone_at: str | None


class CardsOut(BaseModel):
    cards: list[CardOut]


def _live(kind: str, found: Signals) -> dict[str, Any]:
    match kind:
        case "vocab_review":
            return {"reviews_due": found.reviews_due, "new_left": found.new_left}
        case "vocab_screen":
            return {"screened": found.screened, "book_id": found.book.id if found.book else None}
        case "placement":
            return {
                "days_since": found.placement_days,
                "in_progress": found.placement_in_progress,
            }
        case "learner":
            return {"weak_kcs": len(found.weak_kcs)}
        case _:
            return {"book_id": found.book.id if found.book else None}


def _not_found() -> Exception:
    return api_error(status.HTTP_404_NOT_FOUND, "card_not_found", "card not found")


@router.get("/conversations/{conversation_id}/cards")
async def list_cards(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, tz: TimeZone = None
) -> CardsOut:
    """Oldest first; link cards carry live numbers (computed once per request)."""
    try:
        conversation = await get_owned_conversation(session, user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "conversation_not_found", "conversation not found"
        ) from exc
    cards = await service.conversation_cards(session, conversation.id)
    found: Signals | None = None
    if any(c.kind == "link" for c in cards):
        zone = await learner_zone(session, user.id, tz)
        found = await signals(
            session, user.id, rules=get_rules(), catalog=get_grammar_catalog(), tz=zone
        )
        await session.commit()  # stale mastery rows may have been rebuilt
    out = []
    for card in cards:
        item = CardOut.model_validate(service.card_json(card))
        if card.kind == "link" and found is not None:
            item.live = _live(card.params["kind"], found)
        out.append(item)
    return CardsOut(cards=out)


async def _decide(
    session: SessionDep, action: Any, user_id: uuid.UUID, card_id: uuid.UUID
) -> CardOut:
    try:
        card: TutorCard = await action(session, user_id, card_id)
    except CardNotFoundError as exc:
        raise _not_found() from exc
    except CardStateError as exc:
        raise api_error(status.HTTP_409_CONFLICT, exc.code, exc.message) from exc
    return CardOut.model_validate(service.card_json(card))


_CONFLICTS: dict[int | str, dict[str, Any]] = {
    404: {"description": "card_not_found"},
    409: {"description": "card_not_pending, card_not_applied, card_invalid or setting_changed"},
}


@router.post("/cards/{card_id}/apply", responses=_CONFLICTS)
async def apply_card(card_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> CardOut:
    """Carry out a proposal; applying again returns it unchanged."""
    return await _decide(session, service.apply_card, user.id, card_id)


@router.post("/cards/{card_id}/decline", responses=_CONFLICTS)
async def decline_card(card_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> CardOut:
    return await _decide(session, service.decline_card, user.id, card_id)


@router.post("/cards/{card_id}/undo", responses=_CONFLICTS)
async def undo_card(card_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> CardOut:
    """Put back what applying replaced; 409 setting_changed if it was changed since."""
    return await _decide(session, service.undo_card, user.id, card_id)
