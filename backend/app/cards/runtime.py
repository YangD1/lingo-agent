"""The tutor's tools for one turn, backed by the database (ADR 0015 §1).

Bound at the API layer to the learner, conversation and turn: the graph passes only
the model's tool name, arguments and call id. `scope`, when given, limits the practice
and link cards (a planning conversation's candidates, ADR 0015 §6).
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cards import service
from app.cards.quiz import QuizTools
from app.cards.tools import (
    QUIZ_TOOL_NAMES,
    WITHDRAW_TOOL_NAME,
    WORKSPACE_TOOL_NAMES,
    CardDraft,
    CardScope,
    ToolCallError,
    ToolOutcome,
    WithdrawCard,
    draft_card,
    parse_args,
)
from app.workspace.tools import WorkspaceTools

logger = logging.getLogger(__name__)


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
        stop_quiz: Callable[[uuid.UUID], None] | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._turn_id = turn_id
        self._scope = scope
        self._workspace = workspace
        self._quiz = quiz
        # Stops generating a withdrawn quiz card's set (PracticeWorker.cancel).
        self._stop_quiz = stop_quiz
        # One turn's calls run in parallel; put_card's same-proposal check is a read
        # then a write, so they take turns writing.
        self._writing = asyncio.Lock()

    async def run(self, name: str, args: Mapping[str, Any], call_id: str) -> ToolOutcome:
        if name in WORKSPACE_TOOL_NAMES:
            return await self._run_workspace(name, args, call_id)
        if name in QUIZ_TOOL_NAMES:
            return await self._run_quiz(args, call_id)
        if name == WITHDRAW_TOOL_NAME:
            return await self._withdraw(args)
        try:
            draft = draft_card(name, args, await self._scope() if self._scope else None)
        except ToolCallError as exc:
            # The activity row says only "failed"; why goes to the log.
            logger.info("tool call %s refused: %s", name, exc)
            return ToolOutcome(f"Error: {exc}. No card was shown.", ok=False)
        return await self._put(draft, call_id)

    async def _run_workspace(self, name: str, args: Mapping[str, Any], call_id: str) -> ToolOutcome:
        """The workspace tools write documents first, then their card (ADR 0043 §6)."""
        if self._workspace is None:
            return ToolOutcome("Error: the workspace is not available here.", ok=False)
        try:
            result = await self._workspace.run(name, args, call_id)
        except ToolCallError as exc:
            logger.info("tool call %s refused: %s", name, exc)
            return ToolOutcome(f"Error: {exc}.", ok=False)
        outcome, handle = await self._put_card(result.draft, call_id)
        card = outcome.card
        if result.apply and card is not None and card["status"] == "proposed":
            card = await self._apply(uuid.UUID(card["id"]))
        return ToolOutcome(f"(card {handle}) {result.content}", ok=True, card=card)

    async def _apply(self, card_id: uuid.UUID) -> dict[str, Any]:
        async with self._writing, self._sessionmaker() as session:
            return service.card_json(await service.apply_card(session, self._user_id, card_id))

    async def _run_quiz(self, args: Mapping[str, Any], call_id: str) -> ToolOutcome:
        """give_quiz starts a set first, then shows its card (ADR 0044 §4)."""
        if self._quiz is None:
            return ToolOutcome("Error: quizzes are not available here.", ok=False)
        try:
            result = await self._quiz.run(
                args, call_id, await self._scope() if self._scope else None
            )
        except ToolCallError as exc:
            logger.info("tool call give_quiz refused: %s", exc)
            return ToolOutcome(f"Error: {exc}. No card was shown.", ok=False)
        outcome, handle = await self._put_card(result.draft, call_id)
        return ToolOutcome(f"(card {handle}) {result.content}", ok=True, card=outcome.card)

    async def _withdraw(self, args: Mapping[str, Any]) -> ToolOutcome:
        """Takes back a card of this conversation (ADR 0049); the learner sees it change."""
        try:
            parsed = parse_args(WITHDRAW_TOOL_NAME, args)
        except ToolCallError as exc:
            return ToolOutcome(f"Error: {exc}.", ok=False)
        assert isinstance(parsed, WithdrawCard)
        try:
            async with self._writing, self._sessionmaker() as session:
                done = await service.withdraw_card(
                    session, self._conversation_id, parsed.card, parsed.reason
                )
                card = service.card_json(done.card)
        except service.CardNotFoundError:
            return ToolOutcome(
                f"Error: no card {parsed.card!r} in this conversation; use an id from "
                "the cards list.",
                ok=False,
            )
        except service.CardStateError as exc:
            logger.info("withdraw_card refused: %s", exc.message)
            return ToolOutcome(f"Error: {exc.message}.", ok=False)
        if done.set_id is not None and self._stop_quiz is not None:
            self._stop_quiz(done.set_id)
        return ToolOutcome(
            "Card withdrawn; the learner sees it taken back with your reason.",
            ok=True,
            card=card,
        )

    async def _put(self, draft: CardDraft, call_id: str) -> ToolOutcome:
        outcome, _ = await self._put_card(draft, call_id)
        return outcome

    async def _put_card(self, draft: CardDraft, call_id: str) -> tuple[ToolOutcome, str]:
        """The card's outcome, and the id the tutor names it by (withdraw_card): its
        first call's, when the same proposal in one turn reuses a card."""
        async with self._writing, self._sessionmaker() as session:
            card = await service.put_card(
                session,
                user_id=self._user_id,
                conversation_id=self._conversation_id,
                turn_id=self._turn_id,
                tool_call_id=call_id,
                draft=draft,
            )
            content = f"Card shown (card {card.tool_call_id}): {service.describe(card)}."
            if card.status == "proposed":
                content += " Nothing changes until the learner confirms it on the card."
            return ToolOutcome(content, ok=True, card=service.card_json(card)), card.tool_call_id

    async def context(self) -> str:
        async with self._sessionmaker() as session:
            cards = await service.conversation_cards(
                session, self._conversation_id, limit=service.CONTEXT_CARDS
            )
            quizzes = await service.quiz_context(session, cards)
        return service.render_context(cards, quizzes)
