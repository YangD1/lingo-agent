"""Conversations (P0 plan §6.2). Someone else's conversation is always a 404."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, ConfigDict

from app.chat import service
from app.chat.service import ConversationNotFoundError
from app.db.models import Conversation
from app.deps import ChatGraphDep, CurrentTenant, CurrentUser, SessionDep

router = APIRouter(prefix="/conversations", tags=["chat"])


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: str | None
    role: Literal["user", "assistant"]
    content: str


async def _owned(
    session: SessionDep, user: CurrentUser, conversation_id: uuid.UUID
) -> Conversation:
    try:
        return await service.get_owned_conversation(session, user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found") from exc


@router.get("")
async def list_conversations(user: CurrentUser, session: SessionDep) -> list[ConversationOut]:
    rows = await service.list_conversations(session, user.id)
    return [ConversationOut.model_validate(c) for c in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> ConversationOut:
    conversation = await service.create_conversation(session, tenant.id, user.id)
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, graph: ChatGraphDep
) -> list[MessageOut]:
    conversation = await _owned(session, user, conversation_id)
    history = await service.get_history(graph, conversation)
    return [MessageOut(id=m.id, role=m.role, content=m.content) for m in history]


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, graph: ChatGraphDep
) -> None:
    conversation = await _owned(session, user, conversation_id)
    checkpointer = graph.checkpointer
    if not isinstance(checkpointer, BaseCheckpointSaver):  # compiled without persistence
        raise RuntimeError("chat graph has no checkpointer")
    await service.delete_conversation(session, checkpointer, conversation)
