"""The document open in the workspace, for the coach's prompt (ADR 0043 §6).

The frontend says which document is open with each message; it must belong to the
conversation. The text is data, not instructions: the prompt marks it off and says so.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.reading import beginning
from app.db.models import WorkspaceDoc
from app.prompts import load_prompt
from app.services.news.clean import count_words
from app.workspace import service

# Q83g: the coach reads this much of the document each turn.
MAX_CONTEXT_WORDS = 1500


@dataclass(frozen=True)
class WorkspaceFocus:
    doc_id: uuid.UUID
    kind: str
    title: str
    version: int
    text: str
    words: int
    # Only the beginning was given.
    cut: bool = False


class WorkspaceSource(Protocol):
    async def load(self) -> WorkspaceFocus | None:
        """None when the document is gone."""
        ...


class DatabaseWorkspace:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        conversation_id: uuid.UUID,
        doc_id: uuid.UUID,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._conversation_id = conversation_id
        self._doc_id = doc_id

    async def load(self) -> WorkspaceFocus | None:
        async with self._sessionmaker() as session:
            doc = await session.get(WorkspaceDoc, self._doc_id)
            if doc is None or doc.conversation_id != self._conversation_id:
                return None
            content = (await service.get_version(session, doc)).content
        if doc.kind == "reading":
            whole = list(content["paragraphs"])
        else:
            whole = [p for p in str(content["text"]).split("\n\n") if p.strip()]
        kept = beginning(whole, MAX_CONTEXT_WORDS)
        cut = len(kept) < len(whole)
        if kept and count_words(kept[0]) > MAX_CONTEXT_WORDS:
            kept = [" ".join(kept[0].split()[:MAX_CONTEXT_WORDS])]
            cut = True
        return WorkspaceFocus(
            doc.id,
            doc.kind,
            doc.title,
            doc.version,
            "\n\n".join(kept),
            sum(count_words(p) for p in kept),
            cut,
        )


def render_workspace(focus: WorkspaceFocus | None) -> str:
    if focus is None:
        return ""
    what = "the learner's own writing" if focus.kind == "writing" else "a text to read closely"
    note = " Only its beginning is given here." if focus.cut else ""
    return (
        load_prompt("workspace_context")
        .replace("{kind}", focus.kind)
        .replace("{what}", what)
        .replace("{title}", focus.title)
        .replace("{doc_id}", str(focus.doc_id))
        .replace("{version}", str(focus.version))
        .replace("{note}", note)
        .replace("{text}", focus.text)
    )
