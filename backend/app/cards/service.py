"""Tutor cards in the database: written by tool calls, applied / declined / undone by
the learner (ADR 0015 §4)."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import get_grammar_catalog
from app.cards.tools import CardDraft
from app.db.models import TutorCard, UserProfile, UserWordBook
from app.services.vocab.books import get_book

# Recent cards the tutor is reminded of each turn.
CONTEXT_CARDS = 10
GOAL_FIELDS = ("goal", "target_exam", "daily_minutes")


class CardNotFoundError(Exception):
    """Missing *or* someone else's: callers must not tell the two apart."""


class CardStateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --- written by tools ---------------------------------------------------------------------


async def put_card(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn_id: str,
    tool_call_id: str,
    draft: CardDraft,
) -> TutorCard:
    """The card for this tool call, written once; commits.

    The same proposal twice in one turn (same kind and parameters) reuses the first
    card, so the learner isn't asked the same thing twice.
    """
    same = await session.scalar(
        select(TutorCard).where(
            TutorCard.conversation_id == conversation_id,
            TutorCard.turn_id == turn_id,
            TutorCard.kind == draft.kind,
            TutorCard.params == draft.params,
        )
    )
    if same is not None:
        return same
    await session.execute(
        insert(TutorCard)
        .values(
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            kind=draft.kind,
            params=draft.params,
            status="proposed" if draft.has_effect else "info",
        )
        .on_conflict_do_nothing(index_elements=["conversation_id", "tool_call_id"])
    )
    await session.commit()
    card = await session.scalar(
        select(TutorCard).where(
            TutorCard.conversation_id == conversation_id, TutorCard.tool_call_id == tool_call_id
        )
    )
    assert card is not None
    return card


async def conversation_cards(
    session: AsyncSession, conversation_id: uuid.UUID, *, limit: int | None = None
) -> list[TutorCard]:
    """Oldest first; with `limit`, the most recent ones."""
    stmt = select(TutorCard).where(TutorCard.conversation_id == conversation_id)
    if limit is None:
        return list(await session.scalars(stmt.order_by(TutorCard.created_at, TutorCard.id)))
    recent = await session.scalars(
        stmt.order_by(TutorCard.created_at.desc(), TutorCard.id.desc()).limit(limit)
    )
    return list(reversed(recent.all()))


# --- the learner's decisions --------------------------------------------------------------


async def _owned(session: AsyncSession, user_id: uuid.UUID, card_id: uuid.UUID) -> TutorCard:
    card = await session.scalar(
        select(TutorCard)
        .where(TutorCard.id == card_id, TutorCard.user_id == user_id)
        .with_for_update()
    )
    if card is None:
        raise CardNotFoundError(card_id)
    return card


async def apply_card(session: AsyncSession, user_id: uuid.UUID, card_id: uuid.UUID) -> TutorCard:
    """Carry out a proposal, keeping what it replaces; commits. Applying again is a no-op."""
    card = await _owned(session, user_id, card_id)
    if card.status == "applied":
        return card
    if card.status != "proposed":
        raise CardStateError("card_not_pending", "This card has already been handled.")
    if card.kind == "word_book":
        card.before = await _apply_word_book(session, user_id, card.params)
    elif card.kind == "learning_goal":
        card.before = await _apply_goal(session, user_id, card.params)
    card.status = "applied"
    card.decided_at = datetime.now(UTC)
    await session.commit()
    return card


async def decline_card(session: AsyncSession, user_id: uuid.UUID, card_id: uuid.UUID) -> TutorCard:
    card = await _owned(session, user_id, card_id)
    if card.status == "declined":
        return card
    if card.status != "proposed":
        raise CardStateError("card_not_pending", "This card has already been handled.")
    card.status = "declined"
    card.decided_at = datetime.now(UTC)
    await session.commit()
    return card


async def undo_card(session: AsyncSession, user_id: uuid.UUID, card_id: uuid.UUID) -> TutorCard:
    """Put back what applying replaced, unless the setting changed since; commits."""
    card = await _owned(session, user_id, card_id)
    if card.status == "undone":
        return card
    if card.status != "applied" or card.before is None:
        raise CardStateError("card_not_applied", "Only an applied card can be undone.")
    if card.kind == "word_book":
        await _undo_word_book(session, user_id, card.params, card.before)
    elif card.kind == "learning_goal":
        await _undo_goal(session, user_id, card.params, card.before)
    card.status = "undone"
    card.undone_at = datetime.now(UTC)
    await session.commit()
    return card


def _changed_since() -> CardStateError:
    return CardStateError(
        "setting_changed",
        "The setting has changed since this card was applied; adjust it on its page.",
    )


async def _plan(session: AsyncSession, user_id: uuid.UUID) -> UserWordBook | None:
    return await session.scalar(
        select(UserWordBook)
        .where(UserWordBook.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _apply_word_book(
    session: AsyncSession, user_id: uuid.UUID, params: dict[str, Any]
) -> dict[str, Any]:
    book_id: str = params["book_id"]
    if get_book(book_id) is None:  # a book removed since the card was written
        raise CardStateError("card_invalid", "This word book is no longer available.")
    plan = await _plan(session, user_id)
    if plan is None:
        daily_new = params.get("daily_new")
        session.add(UserWordBook(user_id=user_id, book_id=book_id, daily_new=daily_new))
        # `existed: False` - undo removes the plan again.
        return {"existed": False}
    before = {
        "existed": True,
        "book_id": plan.book_id,
        "daily_new": plan.daily_new,
        "screen_offset": plan.screen_offset,
    }
    if plan.book_id != book_id:
        # Screening position is a place in the old book's order (as choose_book does).
        plan.book_id = book_id
        plan.screen_offset = 0
    if params.get("daily_new") is not None:
        plan.daily_new = params["daily_new"]
    return before


async def _undo_word_book(
    session: AsyncSession, user_id: uuid.UUID, params: dict[str, Any], before: dict[str, Any]
) -> None:
    plan = await _plan(session, user_id)
    daily_new = params.get("daily_new")
    if (
        plan is None
        or plan.book_id != params["book_id"]
        or (daily_new is not None and plan.daily_new != daily_new)
    ):
        raise _changed_since()
    if not before["existed"]:
        await session.execute(delete(UserWordBook).where(UserWordBook.user_id == user_id))
        return
    plan.book_id = before["book_id"]
    plan.daily_new = before["daily_new"]
    plan.screen_offset = before["screen_offset"]


async def _profile(session: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    return await session.scalar(
        select(UserProfile)
        .where(UserProfile.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _apply_goal(
    session: AsyncSession, user_id: uuid.UUID, params: dict[str, Any]
) -> dict[str, Any]:
    profile = await _profile(session, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id, interests=[], manual_fields=[])
        session.add(profile)
    fields = [f for f in GOAL_FIELDS if f in params]
    before = {
        "values": {f: getattr(profile, f) for f in fields},
        "manual_fields": list(profile.manual_fields or []),
    }
    for field in fields:
        setattr(profile, field, params[field])
    # The learner confirmed it: their setting now, which reflection leaves alone.
    profile.manual_fields = sorted(set(profile.manual_fields or []) | set(fields))
    return before


async def _undo_goal(
    session: AsyncSession, user_id: uuid.UUID, params: dict[str, Any], before: dict[str, Any]
) -> None:
    profile = await _profile(session, user_id)
    fields = [f for f in GOAL_FIELDS if f in params]
    if profile is None or any(getattr(profile, f) != params[f] for f in fields):
        raise _changed_since()
    for field, value in before["values"].items():
        setattr(profile, field, value)
    profile.manual_fields = before["manual_fields"]


# --- rendering ----------------------------------------------------------------------------


def card_json(card: TutorCard) -> dict[str, Any]:
    """What the chat stream and the cards API send; names resolved from the catalogs."""
    display: dict[str, Any] = {}
    if card.kind == "word_book" and (book := get_book(card.params["book_id"])):
        display["book"] = {"id": book.id, "name_en": book.name_en, "name_zh": book.name_zh}
    if card.kind == "practice" and (kc := get_grammar_catalog().get(card.params["kc_id"])):
        display["kc"] = {"id": kc.id, "name_en": kc.name_en, "name_zh": kc.name_zh, "cefr": kc.cefr}
    return {
        "id": str(card.id),
        "turn_id": card.turn_id,
        "kind": card.kind,
        "params": card.params,
        "status": card.status,
        "display": display,
        "created_at": card.created_at.isoformat() if card.created_at else None,
        "decided_at": card.decided_at.isoformat() if card.decided_at else None,
        "undone_at": card.undone_at.isoformat() if card.undone_at else None,
    }


_STATUS_TEXT = {
    "proposed": "waiting for the learner to confirm",
    "applied": "the learner confirmed it; it is in effect",
    "declined": "the learner declined it",
    "undone": "the learner confirmed it, then undid it",
    "info": "shown",
}


def describe(card: TutorCard) -> str:
    """One line about a card, for the model (tool results and the next turns' context)."""
    p = card.params
    match card.kind:
        case "word_book":
            book = get_book(p["book_id"])
            what = f"switch the word book to {book.name_en if book else p['book_id']}"
            if p.get("daily_new") is not None:
                what += f", {p['daily_new']} new words a day"
        case "learning_goal":
            what = "set " + ", ".join(f"{k}={p[k]!r}" for k in GOAL_FIELDS if k in p)
        case "practice":
            kc = get_grammar_catalog().get(p["kc_id"])
            what = f"practise {kc.name_en if kc else p['kc_id']}"
        case "writing":
            what = "open the line-by-line review of the learner's writing"
        case _:
            what = f"open the {p['kind']} page"
    return f"{what} ({_STATUS_TEXT.get(card.status, card.status)})"


def render_context(cards: Sequence[TutorCard]) -> str:
    return "\n".join(f"- {describe(c)}" for c in cards)
