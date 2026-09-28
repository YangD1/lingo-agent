"""Minimal tutor graph: START -> tutor -> END (P1 adds memory and routing around it).

Per-run dependencies travel in LangGraph's runtime context, not in `configurable`:
`configurable` values can be copied into checkpoint metadata, and the provider
context carries decrypted API keys that must never be persisted (ADR 0004).

    await graph.astream(
        {"messages": [HumanMessage(text)]},
        config={
            "configurable": {"thread_id": str(conversation.id)},
            "metadata": {"user_id": str(user.id)},  # for llm_usage (ADR 0005)
        },
        context=ChatContext(providers=ctx),
        stream_mode="messages",
    )
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import (
    BaseMessage,
    BaseMessageChunk,
    HumanMessage,
    SystemMessage,
    message_chunk_to_message,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.attachments.context import AttachmentSource, render_turn, turn_content
from app.prompts import load_prompt
from app.providers.config import TenantProviderContext
from app.providers.llm import get_llm

TUTOR_NODE = "tutor"


@dataclass(frozen=True)
class ChatContext:
    providers: TenantProviderContext
    # Attachments of this conversation (ADR 0008 §4); None when a caller has none.
    attachments: AttachmentSource | None = None


type ChatGraph = CompiledStateGraph[MessagesState, ChatContext, MessagesState, MessagesState]


async def tutor(state: MessagesState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    # The system prompt is prepended per call rather than stored in the thread, so
    # prompt edits apply to existing conversations too.
    history, has_images = await _with_attachments(state["messages"], runtime.context.attachments)
    # A turn that brings images is answered by a model configured to see them.
    llm = get_llm(runtime.context.providers, "vision" if has_images else "chat")
    messages = [SystemMessage(load_prompt("tutor_system")), *history]
    # astream, not ainvoke: if the learner disconnects, the run is cancelled, and only
    # astream reports that to callbacks (ainvoke's internal gather is cancelled before
    # on_llm_error runs), so llm_usage would miss a call the provider still bills for.
    reply: BaseMessage | None = None
    async for part in llm.astream(messages):
        # Streaming models yield chunks to merge; others yield one complete message.
        if reply is None:
            reply = part
        elif isinstance(reply, BaseMessageChunk) and isinstance(part, BaseMessageChunk):
            reply = reply + part
        else:
            raise TypeError(f"cannot merge {type(part).__name__} into a streamed reply")
    if reply is None:
        raise ValueError("chat model returned no output")
    return {"messages": [message_chunk_to_message(reply)]}


async def _with_attachments(
    messages: Sequence[BaseMessage], source: AttachmentSource | None
) -> tuple[list[BaseMessage], bool]:
    """Expand learner messages with their attachments, for this call only.

    Nothing here is written back to the state: the checkpoint keeps plain text, and
    original images go only with the turn they were sent in.
    """
    human_ids = [m.id for m in messages if isinstance(m, HumanMessage) and m.id]
    if source is None or not human_ids:
        return list(messages), False
    attached = await source.by_message(human_ids)
    if not attached:
        return list(messages), False
    current = human_ids[-1]
    has_images = False
    expanded: list[BaseMessage] = []
    for message in messages:
        items = attached.get(message.id or "") if isinstance(message, HumanMessage) else None
        if not items:
            expanded.append(message)
            continue
        rendered = render_turn(message.text, items)
        images = []
        if message.id == current:
            images = await source.images([a.id for a in items if a.kind == "image"])
            has_images = bool(images)
        expanded.append(HumanMessage(turn_content(rendered, images), id=message.id))
    return expanded, has_images


def build_chat_graph(checkpointer: BaseCheckpointSaver[Any]) -> ChatGraph:
    builder = StateGraph(MessagesState, context_schema=ChatContext)
    builder.add_node(TUTOR_NODE, tutor)
    builder.add_edge(START, TUTOR_NODE)
    builder.add_edge(TUTOR_NODE, END)
    return builder.compile(checkpointer=checkpointer)
