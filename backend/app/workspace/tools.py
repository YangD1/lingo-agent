"""The tutor's workspace tools (ADR 0043 §6): `open_workspace` and `propose_edit`.

Bound to the learner, tenant and conversation of a turn, like the card tools; the
model names what to open, never the text, which is copied from the learner's message
or the conversation's article by code. Each call also leaves a card in the chat.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.rules import get_rules
from app.cards.tools import CardDraft, OpenWorkspace, ProposeEdit, ToolCallError, parse_args
from app.db.models import Conversation, WorkspaceDoc
from app.services.news.clean import count_words
from app.services.reading.versions import reading_level
from app.workspace import edits, service

# A message shorter than this is not "a long text" to open.
MIN_WORDS = 20


@dataclass(frozen=True)
class WorkspaceResult:
    content: str
    draft: CardDraft


class WorkspaceTools:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        learner_texts: Callable[[], Awaitable[list[str]]],
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._conversation_id = conversation_id
        # The learner's messages, latest first; read only when a call needs them.
        self._learner_texts = learner_texts

    async def run(self, name: str, args: Mapping[str, Any], call_id: str) -> WorkspaceResult:
        """Raises ToolCallError, whose message goes back to the model."""
        parsed = parse_args(name, args)
        async with self._sessionmaker() as session:
            match parsed:
                case OpenWorkspace():
                    return await self._open(session, parsed, call_id)
                case ProposeEdit():
                    return await self._propose(session, parsed, call_id)
        raise ToolCallError(f"unknown tool {name!r}")  # pragma: no cover

    async def _open(
        self, session: AsyncSession, args: OpenWorkspace, call_id: str
    ) -> WorkspaceResult:
        doc = await session.scalar(
            select(WorkspaceDoc).where(
                WorkspaceDoc.conversation_id == self._conversation_id,
                WorkspaceDoc.tool_call_id == call_id,
            )
        )
        if doc is None:
            doc = await self._create(session, args, call_id)
        return WorkspaceResult(
            f"Opened the {doc.kind} document {doc.title!r} (id {doc.id}) in the workspace; "
            "the learner sees it beside the chat.",
            CardDraft("workspace", {"doc_id": str(doc.id), "kind": doc.kind, "title": doc.title}),
        )

    async def _create(
        self, session: AsyncSession, args: OpenWorkspace, call_id: str
    ) -> WorkspaceDoc:
        conversation = await session.get(Conversation, self._conversation_id)
        assert conversation is not None and conversation.user_id == self._user_id
        try:
            match args.source:
                case "last_message":
                    text = service.text_for(args.kind, await self._long_text(), args.title)
                    source = "message"
                case "article":
                    if args.kind != "reading" or conversation.article_id is None:
                        raise ToolCallError("this conversation has no article to read")
                    level = await reading_level(session, self._user_id, get_rules())
                    text = await service.article_text(
                        session, self._tenant_id, conversation.article_id, level, args.title
                    )
                    source = "article"
                case "blank":
                    if args.kind != "writing":
                        raise ToolCallError("only a writing document can start blank")
                    text = service.writing_text("", args.title)
                    source = "blank"
        except service.WorkspaceError as exc:
            raise ToolCallError(exc.message) from exc
        return await service.create(
            session,
            conversation,
            args.kind,
            source,
            text,
            created_by="tutor",
            tool_call_id=call_id,
        )

    async def _long_text(self) -> str:
        """The latest of the learner's last two messages that is a long text."""
        for text in (await self._learner_texts())[:2]:
            if count_words(text) >= MIN_WORDS:
                return text
        raise ToolCallError(
            "the learner's last two messages have no long text; ask them to paste it, "
            "or open a blank writing document"
        )

    async def _propose(
        self, session: AsyncSession, args: ProposeEdit, call_id: str
    ) -> WorkspaceResult:
        try:
            doc_id = uuid.UUID(args.doc_id)
        except ValueError:
            doc_id = None
        doc = await session.get(WorkspaceDoc, doc_id) if doc_id else None
        if doc is None or doc.conversation_id != self._conversation_id:
            raise ToolCallError(f"no document {args.doc_id!r} in this conversation")
        items = [edits.Item(e.original, e.replacement, e.reason) for e in args.edits]
        try:
            proposed = await edits.propose(session, doc, items, call_id)
        except service.WorkspaceError as exc:
            raise ToolCallError(exc.message) from exc
        if proposed.edit is None:
            raise ToolCallError("no edit could be proposed: " + "; ".join(proposed.refused))
        count = len(proposed.edit.items)
        content = (
            f"Proposed {count} edit(s) to {doc.title!r}; the learner accepts or declines "
            "each in the workspace. Nothing has changed yet."
        )
        if proposed.refused:
            content += " Not proposed: " + "; ".join(proposed.refused) + "."
        params = {
            "doc_id": str(doc.id),
            "edit_id": str(proposed.edit.id),
            "title": doc.title,
            "count": count,
        }
        return WorkspaceResult(content, CardDraft("workspace_edit", params))
