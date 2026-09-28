from collections.abc import Iterator

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability import setup_tracing, shutdown_tracing
from app.settings import Settings


def test_disabled_by_default() -> None:
    assert setup_tracing(Settings(_env_file=None)) is None


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = setup_tracing(
        Settings(_env_file=None, otel_tracing_enabled=True),
        span_processor=SimpleSpanProcessor(exporter),
    )
    assert isinstance(provider, TracerProvider)
    yield exporter
    shutdown_tracing(provider)


async def test_langgraph_nodes_and_llm_calls_become_spans(
    exporter: InMemorySpanExporter,
) -> None:
    model = GenericFakeChatModel(messages=iter([AIMessage("Hello there")]))

    async def tutor(state: MessagesState) -> dict[str, list[AIMessage]]:
        reply = await model.ainvoke(state["messages"])
        return {"messages": [AIMessage(content=reply.content)]}

    builder = StateGraph(MessagesState)
    builder.add_node("tutor", tutor)
    builder.add_edge(START, "tutor")
    builder.add_edge("tutor", END)
    graph = builder.compile()

    await graph.ainvoke(
        {"messages": [HumanMessage("hi")]},
        config={"metadata": {"tenant_id": "t1", "conversation_id": "c1"}, "tags": ["chat"]},
    )

    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert "LangGraph" in names
    assert "tutor" in names
    assert "GenericFakeChatModel" in names

    # Run metadata reaches the spans, so traces can be filtered per tenant/conversation.
    root = next(s for s in spans if s.name == "LangGraph")
    metadata = str((root.attributes or {}).get("metadata", ""))
    assert "t1" in metadata and "c1" in metadata

    # All spans belong to one trace.
    assert len({s.context.trace_id for s in spans if s.context}) == 1
