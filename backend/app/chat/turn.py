"""One conversation turn: the learner's message in, a streamed tutor reply out."""

import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.messages import AIMessageChunk, HumanMessage
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chat_graph import TUTOR_NODE, ChatContext, ChatGraph
from app.chat.service import thread_config
from app.db.models import Conversation
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


async def begin_turn(session: AsyncSession, conversation: Conversation, text: str) -> None:
    """Title the conversation on its first message and move it to the top of the list.

    Commits, so no transaction (and pooled connection) is held while the reply streams.
    """
    if not conversation.title:
        conversation.title = title_from(text)
    conversation.updated_at = func.now()
    await session.commit()


async def stream_reply(
    graph: ChatGraph,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    providers: TenantProviderContext,
    text: str,
) -> AsyncIterator[TurnEvent]:
    """Tutor tokens as they arrive, then `done`; `error` instead if the model fails.

    If the client disconnects the run is cancelled; LangGraph only checkpoints finished
    nodes, so the learner's message is kept but no half-written reply is.
    """
    message_id: str | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        async for chunk, metadata in graph.astream(
            {"messages": [HumanMessage(text)]},
            {
                **thread_config(conversation_id),
                # llm_usage reads user_id here; conversation_id comes from thread_id.
                "metadata": {"user_id": str(user_id)},
                "tags": ["chat"],
            },
            context=ChatContext(providers),
            stream_mode="messages",
        ):
            if not (
                isinstance(chunk, AIMessageChunk)
                and isinstance(metadata, dict)
                and metadata.get("langgraph_node") == TUTOR_NODE
            ):
                continue
            message_id = message_id or chunk.id
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
    yield DoneEvent(message_id=message_id, usage=usage)
