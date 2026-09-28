"""How attachments enter the conversation (ADR 0008 §4).

The checkpoint only holds the learner's text; attachments hang off the HumanMessage id.
When the tutor runs, every turn gets its attachments' derived text, and the current
turn also gets its images' original bytes (so it is answered by the `vision` route).
"""

import base64
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from app.db.models import Attachment

# Document text per turn: past this it is cut and the model is told so. Retrieval over
# long documents (RAG) replaces this later (ADR 0008 §8).
MAX_TURN_DOCUMENT_CHARS = 20_000


@dataclass(frozen=True)
class TurnAttachment:
    id: uuid.UUID
    kind: str
    mime_type: str
    filename: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnImage:
    data: bytes
    mime_type: str


class AttachmentSource(Protocol):
    async def by_message(self, message_ids: Sequence[str]) -> dict[str, list[TurnAttachment]]: ...

    async def images(self, attachment_ids: Sequence[uuid.UUID]) -> list[TurnImage]: ...


def render_turn(text: str, attachments: Sequence[TurnAttachment]) -> str:
    """The learner's text followed by each attachment's derived text, labelled."""
    parts = [text] if text.strip() else []
    budget = MAX_TURN_DOCUMENT_CHARS
    for number, attachment in enumerate(attachments, start=1):
        body = attachment.text.strip()
        if attachment.kind == "image":
            header = f'[Attachment {number}: image "{attachment.filename}"]'
        elif attachment.kind == "audio":
            header = f"[Attachment {number}: voice message, transcript]"
            if body == text.strip():
                body = "(the message above is this transcript)"
        else:
            shown = body[: max(budget, 0)]
            budget -= len(shown)
            cut = len(shown) < len(body) or attachment.meta.get("truncated")
            note = f", only its first {len(shown)} characters are included" if cut else ""
            header = f'[Attachment {number}: document "{attachment.filename}"{note}]'
            body = shown
        parts.append(f"{header}\n{body}" if body else header)
    return "\n\n".join(parts)


def turn_content(rendered: str, images: Sequence[TurnImage]) -> str | list[str | dict[str, Any]]:
    """HumanMessage content: plain text, or text plus LangChain standard image blocks."""
    if not images:
        return rendered
    return [
        {"type": "text", "text": rendered or "(see the attached image)"},
        *(
            {
                "type": "image",
                "base64": base64.b64encode(image.data).decode("ascii"),
                "mime_type": image.mime_type,
            }
            for image in images
        ),
    ]


class DatabaseAttachments:
    """AttachmentSource over one conversation's rows."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
    ) -> None:
        self._sessionmaker = sessionmaker
        self._conversation_id = conversation_id

    async def by_message(self, message_ids: Sequence[str]) -> dict[str, list[TurnAttachment]]:
        if not message_ids:
            return {}
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                select(Attachment)
                .where(
                    Attachment.conversation_id == self._conversation_id,
                    Attachment.message_id.in_(message_ids),
                )
                .order_by(Attachment.created_at, Attachment.id)
            )
            found: dict[str, list[TurnAttachment]] = {}
            for row in rows:
                assert row.message_id is not None
                found.setdefault(row.message_id, []).append(
                    TurnAttachment(
                        row.id, row.kind, row.mime_type, row.filename, row.text or "", row.meta
                    )
                )
        return found

    async def images(self, attachment_ids: Sequence[uuid.UUID]) -> list[TurnImage]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                select(Attachment)
                .where(
                    Attachment.conversation_id == self._conversation_id,
                    Attachment.id.in_(attachment_ids),
                    Attachment.kind == "image",
                )
                .options(undefer(Attachment.data))
                .order_by(Attachment.created_at, Attachment.id)
            )
            return [TurnImage(row.data, row.mime_type) for row in rows]
