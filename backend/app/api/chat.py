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
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.attachments import AttachmentOut
from app.api.errors import api_error
from app.attachments import service as attachment_service
from app.attachments.context import DatabaseAttachments
from app.attachments.service import AttachmentNotFoundError, AttachmentStateError
from app.chat import service
from app.chat.locks import ConversationLocks
from app.chat.service import ConversationNotFoundError
from app.chat.turn import DoneEvent, begin_turn, new_message_id, stream_reply
from app.db.models import Attachment, Conversation
from app.deps import ChatGraphDep, CurrentTenant, CurrentUser, SessionDep
from app.memory.context import DatabaseLearner
from app.memory.embedding import memory_embedder
from app.memory.reflection import LOCALE_COOKIE, memory_language
from app.memory.worker import ReflectionWorker
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
    attachments: list[AttachmentOut] = []


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
    request: Request, user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> ConversationOut:
    conversation = await service.create_conversation(session, tenant.id, user.id)
    # Starting afresh is when the conversation the learner left gets its summary.
    await _reflection(request).finish_previous(
        user.id,
        except_conversation_id=conversation.id,
        language=memory_language(request.cookies.get(LOCALE_COOKIE)),
    )
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, graph: ChatGraphDep
) -> list[MessageOut]:
    conversation = await _owned(session, user, conversation_id)
    history = await service.get_history(graph, conversation)
    attached = await service.attachments_by_message(session, conversation, history)
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            attachments=[AttachmentOut.of(a) for a in attached.get(m.id or "", [])],
        )
        for m in history
    ]


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

    content: Annotated[str, Field(max_length=4000)] = ""
    # Uploaded and ready attachments of this conversation (ADR 0008 §3).
    attachment_ids: Annotated[
        list[uuid.UUID], Field(max_length=attachment_service.MAX_PER_MESSAGE)
    ] = []

    @model_validator(mode="after")
    def _not_empty(self) -> "MessageIn":
        if not self.content.strip() and not self.attachment_ids:
            raise ValueError("a message needs text or an attachment")
        return self


@dataclass(frozen=True)
class Turn:
    conversation_id: uuid.UUID
    providers: TenantProviderContext
    text: str
    message_id: str


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
    attachments = await _message_attachments(session, conversation, body.attachment_ids)
    # A turn with images is answered by the vision route (ADR 0008 §4).
    task = "vision" if any(a.kind == "image" for a in attachments) else "chat"
    providers = await load_provider_context(session, tenant.id)
    try:
        get_chat_models(providers, task)  # resolves the route (and warms the cache)
    except NoModelConfiguredError as exc:
        what = "image-capable" if task == "vision" else "chat"
        raise _conflict(exc.code, f"No {what} model is configured. Add one in Settings.") from exc
    # A voice message may come without typed text: its transcript is the text.
    text = body.content.strip() or next(
        (a.text or "" for a in attachments if a.kind == "audio"), ""
    )
    locks: ConversationLocks = request.app.state.conversation_locks
    if not locks.acquire(conversation.id):
        raise _conflict("conversation_busy", "A reply is still being generated.")
    try:
        message_id = new_message_id()
        try:
            await begin_turn(
                session, conversation, text, message_id=message_id, attachments=attachments
            )
        except AttachmentStateError as exc:
            raise _conflict(exc.code, exc.message) from exc
        yield Turn(conversation.id, providers, text, message_id)
    finally:
        locks.release(conversation.id)


async def _message_attachments(
    session: SessionDep, conversation: Conversation, attachment_ids: list[uuid.UUID]
) -> list[Attachment]:
    try:
        return await attachment_service.attachments_for_message(
            session, conversation, attachment_ids
        )
    except AttachmentNotFoundError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "attachment_not_found", "attachment not found"
        ) from exc
    except AttachmentStateError as exc:
        if exc.code in ("invalid_attachments", "too_many_images"):
            raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, exc.message) from exc
        raise _conflict(exc.code, exc.message) from exc


@router.post(
    "/{conversation_id}/messages",
    response_class=EventSourceResponse,
    responses={
        404: {"description": "conversation_not_found or attachment_not_found"},
        409: {
            "description": "no_llm_configured, no_vision_model, conversation_busy, "
            "attachment_not_ready or attachment_sent"
        },
        422: {"description": "validation_error, invalid_attachments or too_many_images"},
    },
)
async def send_message(
    turn: Annotated[Turn, Depends(start_turn)],
    request: Request,
    user: CurrentUser,
    graph: ChatGraphDep,
) -> AsyncIterator[ServerSentEvent]:
    """Stream the tutor's reply: `token`* then `done`, or `error` (ADR 0003)."""
    async for event in stream_reply(
        graph,
        conversation_id=turn.conversation_id,
        user_id=user.id,
        providers=turn.providers,
        text=turn.text,
        message_id=turn.message_id,
        attachments=DatabaseAttachments(request.app.state.sessionmaker, turn.conversation_id),
        learner=DatabaseLearner(
            request.app.state.sessionmaker,
            user.id,
            turn.conversation_id,
            memory_embedder(turn.providers),
        ),
    ):
        data = dataclasses.asdict(event)
        yield ServerSentEvent(event=data.pop("event"), data=data)
        if isinstance(event, DoneEvent):
            # After the reply is out, never before: memory work must not delay it.
            _reflection(request).schedule(
                turn.conversation_id,
                language=memory_language(request.cookies.get(LOCALE_COOKIE)),
            )


def _reflection(request: Request) -> ReflectionWorker:
    worker: ReflectionWorker = request.app.state.reflection_worker
    return worker
