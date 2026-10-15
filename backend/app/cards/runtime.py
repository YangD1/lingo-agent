"""The tutor's tools for one turn, backed by the database (ADR 0015 §1).

Bound at the API layer to the learner, conversation and turn: the graph passes only
the model's tool name, arguments and call id. `scope`, when given, limits the practice
and link cards (a planning conversation's candidates, ADR 0015 §6).
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cards import service
from app.cards.quiz import QuizTools
from app.cards.tools import (
    QUIZ_TOOL_NAMES,
    WORKSPACE_TOOL_NAMES,
    CardDraft,
    CardScope,
    ToolCallError,
    ToolOutcome,
    draft_card,
)
from app.workspace.tools import WorkspaceTools


class DatabaseTutorTools:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        turn_id: str,
        scope: Callable[[], Awaitable[CardScope]] | None = None,
        workspace: WorkspaceTools | None = None,
        quiz: QuizTools | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._turn_id = turn_id
        self._scope = scope
        self._workspace = workspace
        self._quiz = quiz
        # One turn's calls run in parallel; put_card's same-proposal check is a read
        # then a write, so they take turns writing.
        self._writing = asyncio.Lock()

    async def run(self, name: str, args: Mapping[str, Any], call_id: str) -> ToolOutcome:
        if name in WORKSPACE_TOOL_NAMES:
            return await self._run_workspace(name, args, call_id)
        if name in QUIZ_TOOL_NAMES:
            return await self._run_quiz(args, call_id)
        try:
            draft = draft_card(name, args, await self._scope() if self._scope else None)
        except ToolCallError as exc:
            return ToolOutcome(f"Error: {exc}. No card was shown.", ok=False)
        return await self._put(draft, call_id)

    async def _run_workspace(self, name: str, args: Mapping[str, Any], call_id: str) -> ToolOutcome:
        """The workspace tools write documents first, then their card (ADR 0043 §6)."""
        if self._workspace is None:
            return ToolOutcome("Error: the workspace is not available here.", ok=False)
        try:
            result = await self._workspace.run(name, args, call_id)
        except ToolCallError as exc:
            return ToolOutcome(f"Error: {exc}.", ok=False)
        outcome = await self._put(result.draft, call_id)
        return ToolOutcome(result.content, ok=True, card=outcome.card)

    async def _run_quiz(self, args: Mapping[str, Any], call_id: str) -> ToolOutcome:
        """give_quiz starts a set first, then shows its card (ADR 0044 §4)."""
        if self._quiz is None:
            return ToolOutcome("Error: quizzes are not available here.", ok=False)
        try:
            result = await self._quiz.run(
                args, call_id, await self._scope() if self._scope else None
            )
        except ToolCallError as exc:
            return ToolOutcome(f"Error: {exc}. No card was shown.", ok=False)
        outcome = await self._put(result.draft, call_id)
        return ToolOutcome(result.content, ok=True, card=outcome.card)

    async def _put(self, draft: CardDraft, call_id: str) -> ToolOutcome:
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
            quizzes = await service.quiz_context(session, cards)
        return service.render_context(cards, quizzes)
