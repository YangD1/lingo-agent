"""One conversation turn: the learner's message in, a streamed tutor reply out."""

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

import anyio
from langchain_core.messages import AIMessageChunk, HumanMessage
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chat_graph import TUTOR_NODE, ChatContext, ChatGraph
from app.attachments.context import AttachmentSource
from app.attachments.service import link_to_message
from app.chat.service import thread_config
from app.db.models import Attachment, Conversation
from app.providers.config import TenantProviderContext

logger = logging.getLogger(__name__)

TITLE_LENGTH = 40


@dataclass(frozen=True)
class TokenEvent:
    text: str
    event: Literal["token"] = "token"


@dataclass(frozen=True)
class DoneEvent:
    message_id: str | None
    usage: dict[str, int] = field(default_factory=dict)
    event: Literal["done"] = "done"


@dataclass(frozen=True)
class ErrorEvent:
    code: str
    message: str
    event: Literal["error"] = "error"


type TurnEvent = TokenEvent | DoneEvent | ErrorEvent


def title_from(text: str) -> str:
    """First TITLE_LENGTH characters of the first message (no extra LLM call)."""
    return re.sub(r"\s+", " ", text).strip()[:TITLE_LENGTH]


def new_message_id() -> str:
    """Id of the learner's HumanMessage; attachments point at it (ADR 0008 §4)."""
    return str(uuid.uuid4())


async def begin_turn(
    session: AsyncSession,
    conversation: Conversation,
    text: str,
    *,
    message_id: str | None = None,
    attachments: list[Attachment] | None = None,
) -> None:
    """Title the conversation on its first message, mark the message's attachments as
    sent and move the conversation to the top of the list.

    Commits, so no transaction (and pooled connection) is held while the reply streams.
    Raises AttachmentStateError if an attachment was sent by a concurrent request.
    """
    attachments = attachments or []
    if not conversation.title:
        # An image-only message titles the conversation with the file's name.
        conversation.title = title_from(text) or (
            title_from(attachments[0].filename) if attachments else ""
        )
    if attachments:
        assert message_id is not None
        await link_to_message(session, attachments, message_id)
    conversation.updated_at = func.now()
    await session.commit()


# Upper bound on waiting for LangGraph to unwind a cancelled run.
_CANCEL_GRACE_SECONDS = 5.0


async def stream_reply(
    graph: ChatGraph,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    providers: TenantProviderContext,
    text: str,
    message_id: str | None = None,
    attachments: AttachmentSource | None = None,
) -> AsyncIterator[TurnEvent]:
    """Tutor tokens as they arrive, then `done`; `error` instead if the model fails.

    The graph runs in a task of its own. When the consumer goes away (the client
    disconnected and FastAPI cancelled the SSE producer), that task is cancelled
    explicitly. Relying on the cancellation to propagate is not enough: FastAPI cancels
    through an anyio cancel scope, which is level-triggered, so LangGraph's own cleanup
    awaits get cancelled too and its node task - with the provider still streaming,
    and billing - would be left running.

    LangGraph only checkpoints finished nodes, so after a disconnect the learner's
    message is kept but no half-written reply is.
    """
    queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()  # None marks the end

    async def produce() -> None:
        try:
            async for event in _run_graph(
                graph,
                conversation_id=conversation_id,
                user_id=user_id,
                providers=providers,
                text=text,
                message_id=message_id,
                attachments=attachments,
            ):
                queue.put_nowait(event)
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(produce(), name=f"chat-turn-{conversation_id}")
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        if not task.done():
            task.cancel()
        # Shielded: under a cancelled anyio scope every unshielded await is cancelled.
        with anyio.CancelScope(shield=True), anyio.move_on_after(_CANCEL_GRACE_SECONDS):
            await asyncio.wait({task})
        if task.done() and not task.cancelled() and task.exception() is not None:
            logger.error("chat turn task failed", exc_info=task.exception())


async def _run_graph(
    graph: ChatGraph,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    providers: TenantProviderContext,
    text: str,
    message_id: str | None,
    attachments: AttachmentSource | None,
) -> AsyncIterator[TurnEvent]:
    reply_id: str | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        async for chunk, metadata in graph.astream(
            {"messages": [HumanMessage(text, id=message_id)]},
            {
                **thread_config(conversation_id),
                # llm_usage reads user_id here; conversation_id comes from thread_id.
                "metadata": {"user_id": str(user_id)},
                "tags": ["chat"],
            },
            context=ChatContext(providers, attachments),
            stream_mode="messages",
        ):
            if not (
                isinstance(chunk, AIMessageChunk)
                and isinstance(metadata, dict)
                and metadata.get("langgraph_node") == TUTOR_NODE
            ):
                continue
            reply_id = reply_id or chunk.id
            if chunk.usage_metadata:
                usage["input_tokens"] += chunk.usage_metadata["input_tokens"]
                usage["output_tokens"] += chunk.usage_metadata["output_tokens"]
            if chunk.text:
                yield TokenEvent(chunk.text)
    except Exception:
        # Details stay in the server log (and llm_usage); vendor errors can echo input.
        logger.exception("chat turn failed for conversation %s", conversation_id)
        yield ErrorEvent(
            code="llm_unavailable",
            message="The tutor could not reply right now. Please try again.",
        )
        return
    yield DoneEvent(message_id=reply_id, usage=usage)
