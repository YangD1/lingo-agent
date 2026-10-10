"""speaking_coach (task 58.3): a speaking conversation's partner plays the scenario in
short spoken English, without tools, in English whatever the chat language, and speaks
first."""

import uuid
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.adaptive.rules import get_rules
from app.agents.chat_graph import SPEAKING_COACH_NODE, ChatContext, ChatGraph
from app.agents.routing import Route, route_for
from app.chat.speaking import SpeakingFocus, focus_for
from app.memory.context import LearnerContext
from app.providers.config import TenantProviderContext
from tests.integration.test_chat_graph import (
    TOOLS_MARKER,
    FakeTools,
    RecordingChatModel,
    _clear_caches,  # noqa: F401
    checkpointer,  # noqa: F401
    graph,  # noqa: F401
    providers,  # noqa: F401
    thread,
    use_model,
)

__all__ = ["AsyncPostgresSaver"]


class FakeSpeaking:
    def __init__(self, scenario_id: str | None = "ordering_food", *, fail: bool = False) -> None:
        self.scenario_id = scenario_id
        self.fail = fail

    async def load(self) -> SpeakingFocus:
        if self.fail:
            raise RuntimeError("database down")
        return focus_for(self.scenario_id, "A2", get_rules())


class ChineseLearner:
    """A learner who chose to chat mainly in Chinese."""

    async def load(self, query: str) -> LearnerContext:
        return LearnerContext(chat_language="zh")


def speaking(
    ctx: TenantProviderContext, source: FakeSpeaking | None = None, **kw: Any
) -> ChatContext:
    return ChatContext(ctx, route=Route.SPEAKING_COACH, speaking=source or FakeSpeaking(), **kw)


def test_speaking_conversations_route_to_speaking_coach() -> None:
    assert route_for(None, None, speaking=True) is Route.SPEAKING_COACH
    assert route_for(None, None) is Route.TUTOR


async def test_the_coach_plays_the_scenario_without_tools_in_english(
    graph: ChatGraph,  # noqa: F811
    providers: TenantProviderContext,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = RecordingChatModel(reply="Sure. Anything to drink?")
    use_model(monkeypatch, model)

    await graph.ainvoke(
        {"messages": [HumanMessage("I want a burger.")]},
        thread(uuid.uuid4()),
        context=speaking(providers, tools=FakeTools(), learner=ChineseLearner()),
    )

    [sent] = model.seen
    prompt = str(sent[0].content)
    assert "speaking partner" in prompt and "recast" in prompt
    assert "A waiter at a casual restaurant." in prompt
    assert "Could I have ..., please?" in prompt
    assert "At most 2 sentences per reply" in prompt  # A2
    assert "mainly in English" in prompt and "mainly in Chinese" not in prompt
    assert TOOLS_MARKER not in prompt
    assert "patient, encouraging English tutor" not in prompt  # not the tutor's prompt


async def test_free_talk_and_a_failed_load_still_get_a_partner(
    graph: ChatGraph,  # noqa: F811
    providers: TenantProviderContext,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = RecordingChatModel()
    use_model(monkeypatch, model)

    for source in (FakeSpeaking(None), FakeSpeaking(fail=True)):
        await graph.ainvoke(
            {"messages": [HumanMessage("Hi")]},
            thread(uuid.uuid4()),
            context=speaking(providers, source),
        )

    for sent in model.seen:
        prompt = str(sent[0].content)
        assert "free talk" in prompt and "speaking partner" in prompt


async def test_the_coach_opens_with_the_scenario_and_streams_as_itself(
    graph: ChatGraph,  # noqa: F811
    providers: TenantProviderContext,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = RecordingChatModel(reply="Hi, I'm your server today. What can I get you to drink?")
    use_model(monkeypatch, model)
    thread_id = uuid.uuid4()

    nodes: set[str] = set()
    async for _namespace, (_chunk, metadata) in graph.astream(
        {"messages": []},
        thread(thread_id),
        context=speaking(providers),
        stream_mode="messages",
        subgraphs=True,
    ):
        assert isinstance(metadata, dict)
        nodes.add(metadata["langgraph_node"])

    assert nodes == {SPEAKING_COACH_NODE}
    [sent] = model.seen
    assert [m.type for m in sent] == ["system", "human"]
    cue = str(sent[1].content)
    assert "not from the learner" in cue and "you'll be their server" in cue
    stored = (await graph.aget_state(thread(thread_id))).values["messages"]
    assert [m.type for m in stored] == ["ai"]
