"""One conversation turn: the learner's message in, a streamed tutor reply out."""

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

import anyio
from langchain_core.messages import AIMessageChunk, HumanMessage
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity.service import ActivitySink
from app.agents.chat_graph import COACH_NODES, ChatContext, ChatGraph
from app.agents.routing import Route
from app.attachments.context import AttachmentSource
from app.attachments.service import link_to_message
from app.cards.tools import TutorTools
from app.chat.planning import PlanningSource
from app.chat.practice import PracticeSource
from app.chat.reading import ReadingSource
from app.chat.service import REPLY_PART_SEPARATOR, thread_config
from app.chat.speaking import SpeakingSource
from app.chat.writing import WritingSource
from app.db.models import Attachment, Conversation
from app.memory.context import LearnerSource
from app.providers.config import TenantProviderContext

logger = logging.getLogger(__name__)

TITLE_LENGTH = 40


@dataclass(frozen=True)
class TokenEvent:
    text: str
    event: Literal["token"] = "token"


@dataclass(frozen=True)
class ActivityEvent:
    """A step of this turn, as it happens (ADR 0013 §3); shaped like the activity API."""

    turn_id: str
    name: str
    kind: str
    call_id: str
    status: str
    duration_ms: int | None
    summary: dict[str, Any]
    event: Literal["activity"] = "activity"


@dataclass(frozen=True)
class CardEvent:
    """A card a tool call put in the conversation (ADR 0015 §5); shaped like the cards
    API's items."""

    card: dict[str, Any]
    event: Literal["card"] = "card"


@dataclass(frozen=True)
class DoneEvent:
    message_id: str | None
    # The learner message's id: what later background activity is filed under.
    turn_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    event: Literal["done"] = "done"


@dataclass(frozen=True)
class ErrorEvent:
    code: str
    message: str
    event: Literal["error"] = "error"


type TurnEvent = TokenEvent | ActivityEvent | CardEvent | DoneEvent | ErrorEvent


# The turn id of a practice opening, which has no learner message to be named after;
# a conversation opens once at most.
OPENING_TURN_ID = "opening"
# Recorded in llm_usage instead of "chat": the tutor speaking first is not a turn the
# learner took, so it does not count on the dashboard.
OPENING_USAGE_TASK = "practice_opening"
# Likewise for a planning conversation's opening (ADR 0015 §7).
PLAN_OPENING_USAGE_TASK = "plan_opening"
# And for a speaking conversation's (ADR 0029 §7).
SPEAKING_OPENING_USAGE_TASK = "speaking_opening"


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
    text: str | None,
    message_id: str | None = None,
    attachments: AttachmentSource | None = None,
    learner: LearnerSource | None = None,
    activity: ActivitySink | None = None,
    practice: PracticeSource | None = None,
    tools: TutorTools | None = None,
    planning: PlanningSource | None = None,
    route: Route = Route.TUTOR,
    classify: bool = False,
    writing: WritingSource | None = None,
    reading: ReadingSource | None = None,
    speaking: SpeakingSource | None = None,
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

    `text` None is an opening (of a practice, planning or speaking conversation): the tutor
    speaks first, no learner message is added, and `message_id` is OPENING_TURN_ID.
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
                learner=learner,
                activity=activity,
                practice=practice,
                tools=tools,
                planning=planning,
                route=route,
                classify=classify,
                writing=writing,
                reading=reading,
                speaking=speaking,
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
    text: str | None,
    message_id: str | None,
    attachments: AttachmentSource | None,
    learner: LearnerSource | None,
    activity: ActivitySink | None,
    practice: PracticeSource | None,
    tools: TutorTools | None,
    planning: PlanningSource | None,
    route: Route,
    classify: bool,
    writing: WritingSource | None,
    reading: ReadingSource | None,
    speaking: SpeakingSource | None,
) -> AsyncIterator[TurnEvent]:
    reply_id: str | None = None
    text_id: str | None = None  # the tutor message whose text is streaming
    usage = {"input_tokens": 0, "output_tokens": 0}
    opening = (
        PLAN_OPENING_USAGE_TASK
        if planning is not None
        else SPEAKING_OPENING_USAGE_TASK
        if speaking is not None
        else OPENING_USAGE_TASK
    )
    try:
        # subgraphs=True: tokens and custom events come from inside the coach subgraphs.
        async for _namespace, mode, part in graph.astream(
            {"messages": [] if text is None else [HumanMessage(text, id=message_id)]},
            {
                **thread_config(conversation_id),
                # llm_usage reads these; conversation_id comes from thread_id.
                "metadata": {"user_id": str(user_id)}
                | ({"usage_task": opening} if text is None else {}),
                "tags": ["chat"],
            },
            context=ChatContext(
                providers=providers,
                attachments=attachments,
                learner=learner,
                activity=activity,
                practice=practice,
                tools=tools,
                planning=planning,
                route=route,
                classify=classify,
                writing=writing,
                reading=reading,
                speaking=speaking,
            ),
            stream_mode=["messages", "custom"],
            subgraphs=True,
        ):
            if mode == "custom":
                if isinstance(part, dict) and "activity" in part:
                    yield ActivityEvent(**part["activity"])
                if isinstance(part, dict) and "card" in part:
                    yield CardEvent(part["card"])
                continue
            if not isinstance(part, tuple):
                continue
            chunk, metadata = part
            if not (
                isinstance(chunk, AIMessageChunk)
                and isinstance(metadata, dict)
                and metadata.get("langgraph_node") in COACH_NODES
            ):
                continue
            # With tool calls a turn has several tutor messages; history shows them as
            # one, under the last one's id, their texts joined like here.
            if chunk.text and chunk.id != text_id:
                if text_id is not None:
                    yield TokenEvent(REPLY_PART_SEPARATOR)
                text_id = chunk.id
            reply_id = chunk.id or reply_id
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
    yield DoneEvent(message_id=reply_id, turn_id=message_id, usage=usage)
