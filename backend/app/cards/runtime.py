"""The tutor's tools for one turn, backed by the database (ADR 0015 §1).

Bound at the API layer to the learner, conversation and turn: the graph passes only
the model's tool name, arguments and call id.
"""

import asyncio
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cards import service
from app.cards.tools import CardScope, ToolCallError, ToolOutcome, draft_card


class DatabaseTutorTools:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        turn_id: str,
        scope: CardScope | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._turn_id = turn_id
        self._scope = scope
        # One turn's calls run in parallel; put_card's same-proposal check is a read
        # then a write, so they take turns writing.
        self._writing = asyncio.Lock()

    async def run(self, name: str, args: Mapping[str, Any], call_id: str) -> ToolOutcome:
        try:
            draft = draft_card(name, args, self._scope)
        except ToolCallError as exc:
            return ToolOutcome(f"Error: {exc}. No card was shown.", ok=False)
        async with self._writing, self._sessionmaker() as session:
            card = await service.put_card(
                session,
                user_id=self._user_id,
                conversation_id=self._conversation_id,
                turn_id=self._turn_id,
                tool_call_id=call_id,
                draft=draft,
            )
            content = f"Card shown: {service.describe(card)}."
            if card.status == "proposed":
                content += " Nothing changes until the learner confirms it on the card."
            return ToolOutcome(content, ok=True, card=service.card_json(card))

    async def context(self) -> str:
        async with self._sessionmaker() as session:
            cards = await service.conversation_cards(
                session, self._conversation_id, limit=service.CONTEXT_CARDS
            )
        return service.render_context(cards)
