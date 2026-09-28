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

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.prompts import load_prompt
from app.providers.config import TenantProviderContext
from app.providers.llm import get_llm

TUTOR_NODE = "tutor"


@dataclass(frozen=True)
class ChatContext:
    providers: TenantProviderContext


type ChatGraph = CompiledStateGraph[MessagesState, ChatContext, MessagesState, MessagesState]


async def tutor(state: MessagesState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    # The system prompt is prepended per call rather than stored in the thread, so
    # prompt edits apply to existing conversations too.
    llm = get_llm(runtime.context.providers, "chat")
    reply = await llm.ainvoke([SystemMessage(load_prompt("tutor_system")), *state["messages"]])
    return {"messages": [reply]}


def build_chat_graph(checkpointer: BaseCheckpointSaver[Any]) -> ChatGraph:
    builder = StateGraph(MessagesState, context_schema=ChatContext)
    builder.add_node(TUTOR_NODE, tutor)
    builder.add_edge(START, TUTOR_NODE)
    builder.add_edge(TUTOR_NODE, END)
    return builder.compile(checkpointer=checkpointer)
