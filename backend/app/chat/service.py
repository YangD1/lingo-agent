"""Conversation CRUD. Messages live in the LangGraph checkpoint, not in our tables."""

import uuid
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import GrammarKC
from app.agents.chat_graph import ChatGraph
from app.db.models import Attachment, Conversation


class ConversationNotFoundError(Exception):
    """Missing *or* owned by someone else: callers must not tell the two apart."""


@dataclass(frozen=True)
class ChatMessage:
    id: str | None
    role: Literal["user", "assistant"]
    content: str


_ROLES: dict[str, Literal["user", "assistant"]] = {"human": "user", "ai": "assistant"}


def thread_config(conversation_id: uuid.UUID) -> RunnableConfig:
    """LangGraph thread_id is the conversation id."""
    return {"configurable": {"thread_id": str(conversation_id)}}


async def list_conversations(session: AsyncSession, user_id: uuid.UUID) -> list[Conversation]:
    rows = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
    )
    return list(rows)


async def create_conversation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    focus: GrammarKC | None = None,
    locale: str | None = None,
) -> Conversation:
    """A free chat, or with `focus` a practice conversation on that grammar point,
    titled in the UI's `locale` (the list shows titles as they are)."""
    conversation = Conversation(tenant_id=tenant_id, user_id=user_id)
    if focus is not None:
        conversation.focus_kc_id = focus.id
        conversation.title = practice_title(focus, locale)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


def practice_title(kc: GrammarKC, locale: str | None) -> str:
    if locale and locale.lower().startswith("zh"):
        return f"练习：{kc.name_zh}"  # noqa: RUF001 (Chinese punctuation)
    return f"Practice: {kc.name_en}"


async def unstarted_practice(
    session: AsyncSession, graph: ChatGraph, user_id: uuid.UUID, kc_id: str
) -> Conversation | None:
    """The learner's latest practice conversation on `kc_id`, if they haven't said
    anything in it yet (the tutor's opening may be there): opening the same practice
    again returns to it instead of leaving empty conversations behind (Q19c)."""
    latest = await session.scalar(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.focus_kc_id == kc_id)
        .order_by(Conversation.created_at.desc(), Conversation.id)
        .limit(1)
    )
    if latest is None:
        return None
    history = await get_history(graph, latest)
    return None if any(m.role == "user" for m in history) else latest


async def get_owned_conversation(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise ConversationNotFoundError
    return conversation


# Between the texts of one turn's tutor messages (a reply around tool calls).
REPLY_PART_SEPARATOR = "\n\n"


def to_chat_messages(messages: list[BaseMessage]) -> list[ChatMessage]:
    """User-visible turns only (system/tool messages are internal).

    A turn with tool calls has several tutor messages (ADR 0015 §5); they show as one,
    under the last one's id, with the calls themselves left out.
    """
    out: list[ChatMessage] = []
    for m in messages:
        if m.type not in _ROLES:
            continue
        role = _ROLES[m.type]
        if role == "assistant" and out and out[-1].role == "assistant":
            parts = [p for p in (out[-1].content, m.text) if p]
            out[-1] = ChatMessage(id=m.id, role=role, content=REPLY_PART_SEPARATOR.join(parts))
            continue
        out.append(ChatMessage(id=m.id, role=role, content=m.text))
    return out


async def get_history(graph: ChatGraph, conversation: Conversation) -> list[ChatMessage]:
    state = await graph.aget_state(thread_config(conversation.id))
    return to_chat_messages(state.values.get("messages", []))


async def attachments_by_message(
    session: AsyncSession, conversation: Conversation, history: list[ChatMessage]
) -> dict[str, list[Attachment]]:
    """Sent attachments of the learner's messages, keyed by message id."""
    ids = [m.id for m in history if m.role == "user" and m.id]
    if not ids:
        return {}
    rows = await session.scalars(
        select(Attachment)
        .where(Attachment.conversation_id == conversation.id, Attachment.message_id.in_(ids))
        .order_by(Attachment.created_at, Attachment.id)
    )
    found: dict[str, list[Attachment]] = {}
    for row in rows:
        found.setdefault(row.message_id or "", []).append(row)
    return found


async def delete_conversation(
    session: AsyncSession, checkpointer: BaseCheckpointSaver[str], conversation: Conversation
) -> None:
    # Checkpoints first: if that fails the row survives and the user can retry, instead
    # of leaving an orphaned thread nobody can reach or delete.
    await checkpointer.adelete_thread(str(conversation.id))
    await session.delete(conversation)
    await session.commit()
