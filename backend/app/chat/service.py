"""Conversation CRUD. Messages live in the LangGraph checkpoint, not in our tables."""

import uuid
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chat_graph import ChatGraph
from app.db.models import Conversation


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
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> Conversation:
    conversation = Conversation(tenant_id=tenant_id, user_id=user_id)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def get_owned_conversation(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise ConversationNotFoundError
    return conversation


def to_chat_messages(messages: list[BaseMessage]) -> list[ChatMessage]:
    """User-visible turns only (system/tool messages are internal)."""
    return [
        ChatMessage(id=m.id, role=_ROLES[m.type], content=m.text)
        for m in messages
        if m.type in _ROLES
    ]


async def get_history(graph: ChatGraph, conversation: Conversation) -> list[ChatMessage]:
    state = await graph.aget_state(thread_config(conversation.id))
    return to_chat_messages(state.values.get("messages", []))


async def delete_conversation(
    session: AsyncSession, checkpointer: BaseCheckpointSaver[str], conversation: Conversation
) -> None:
    # Checkpoints first: if that fails the row survives and the user can retry, instead
    # of leaving an orphaned thread nobody can reach or delete.
    await checkpointer.adelete_thread(str(conversation.id))
    await session.delete(conversation)
    await session.commit()
