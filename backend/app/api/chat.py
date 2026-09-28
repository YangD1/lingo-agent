"""Conversations (P0 plan §6.2). Someone else's conversation is always a 404."""

import dataclasses
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import api_error
from app.chat import service
from app.chat.locks import ConversationLocks
from app.chat.service import ConversationNotFoundError
from app.chat.turn import begin_turn, stream_reply
from app.db.models import Conversation
from app.deps import ChatGraphDep, CurrentTenant, CurrentUser, SessionDep
from app.providers.config import TenantProviderContext
from app.providers.errors import NoModelConfiguredError
from app.providers.llm import get_chat_models
from app.providers.tenant import load_provider_context

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
        raise api_error(
            status.HTTP_404_NOT_FOUND, "conversation_not_found", "conversation not found"
        ) from exc


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


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Field(min_length=1, max_length=4000)]


@dataclass(frozen=True)
class Turn:
    conversation_id: uuid.UUID
    providers: TenantProviderContext
    text: str


def _conflict(code: str, message: str) -> HTTPException:
    return api_error(status.HTTP_409_CONFLICT, code, message)


async def start_turn(
    conversation_id: uuid.UUID,
    body: MessageIn,
    request: Request,
    response: Response,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
) -> AsyncIterator[Turn]:
    """Everything that can fail with a proper HTTP status, before the stream starts.

    FastAPI sends the SSE response headers (200) before running the endpoint body, so
    404/409 must be raised here. Being a yield dependency on the request scope, the
    lock is released only after the stream ends - including client disconnects.
    """
    # Appended to FastAPI's own "no-cache". Without no-transform, Next's rewrite proxy
    # gzips the stream and buffers the whole reply (ADR 0003). Set here because the
    # endpoint body runs only after the headers are sent.
    response.headers["Cache-Control"] = "no-transform"
    conversation = await _owned(session, user, conversation_id)
    providers = await load_provider_context(session, tenant.id)
    try:
        get_chat_models(providers, "chat")  # resolves the route (and warms the cache)
    except NoModelConfiguredError as exc:
        raise _conflict(
            exc.code, "No chat model is configured. Add a model connection in Settings."
        ) from exc
    locks: ConversationLocks = request.app.state.conversation_locks
    if not locks.acquire(conversation.id):
        raise _conflict("conversation_busy", "A reply is still being generated.")
    try:
        await begin_turn(session, conversation, body.content)
        yield Turn(conversation.id, providers, body.content)
    finally:
        locks.release(conversation.id)


@router.post(
    "/{conversation_id}/messages",
    response_class=EventSourceResponse,
    responses={409: {"description": "no_llm_configured or conversation_busy"}},
)
async def send_message(
    turn: Annotated[Turn, Depends(start_turn)], user: CurrentUser, graph: ChatGraphDep
) -> AsyncIterator[ServerSentEvent]:
    """Stream the tutor's reply: `token`* then `done`, or `error` (ADR 0003)."""
    async for event in stream_reply(
        graph,
        conversation_id=turn.conversation_id,
        user_id=user.id,
        providers=turn.providers,
        text=turn.text,
    ):
        data = dataclasses.asdict(event)
        yield ServerSentEvent(event=data.pop("event"), data=data)
