import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any, ClassVar

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.activity.service import ContextRead, Step
from app.adaptive.kc.catalog import get_grammar_catalog
from app.agents.chat_graph import TUTOR_NODE, ChatContext, ChatGraph, build_chat_graph
from app.chat.practice import Mistake, PracticeFocus
from app.db.urls import to_psycopg_conninfo
from app.memory.context import MAX_FACTS_CHARS, LearnerContext
from app.providers import llm
from app.providers.config import TenantProviderContext
from tests.conftest import CHECKPOINT_TABLES, TEST_DATABASE_URL
from tests.unit.provider_fixtures import conn, make_ctx

# Stands in for a decrypted provider key; distinctive so any leak is easy to find.
KEY_MARKER = "never-persist-this-provider-key-marker-42"


class RecordingChatModel(BaseChatModel):
    """Replies with a fixed text and remembers what it was sent."""

    reply: str = "Nice to meet you!"
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "recording"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(self.reply))])


@pytest.fixture
async def checkpointer(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> AsyncIterator[AsyncPostgresSaver]:
    # db_session: its teardown truncates the checkpoint tables after each test.
    async with AsyncPostgresSaver.from_conn_string(to_psycopg_conninfo(TEST_DATABASE_URL)) as saver:
        yield saver


@pytest.fixture
def graph(checkpointer: AsyncPostgresSaver) -> ChatGraph:
    return build_chat_graph(checkpointer)


@pytest.fixture
def providers() -> TenantProviderContext:
    return make_ctx(conn("openai", key=KEY_MARKER))


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    llm.reset_caches()
    yield
    llm.reset_caches()


def use_model(monkeypatch: pytest.MonkeyPatch, model: BaseChatModel) -> list[TenantProviderContext]:
    """Serve `model` for every task; returns the provider contexts the graph passed in."""
    contexts: list[TenantProviderContext] = []

    def fake_get_chat_models(ctx: TenantProviderContext, task: str) -> tuple[BaseChatModel, ...]:
        contexts.append(ctx)
        return (model,)

    monkeypatch.setattr(llm, "get_chat_models", fake_get_chat_models)
    return contexts


def thread(thread_id: uuid.UUID) -> RunnableConfig:
    return {"configurable": {"thread_id": str(thread_id)}}


async def test_turns_accumulate_per_thread(
    graph: ChatGraph, providers: TenantProviderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_model(monkeypatch, RecordingChatModel())
    first, second = uuid.uuid4(), uuid.uuid4()
    context = ChatContext(providers=providers)

    await graph.ainvoke({"messages": [HumanMessage("Hi")]}, thread(first), context=context)
    await graph.ainvoke(
        {"messages": [HumanMessage("How are you?")]}, thread(first), context=context
    )
    await graph.ainvoke({"messages": [HumanMessage("Hello")]}, thread(second), context=context)

    first_state = await graph.aget_state(thread(first))
    assert [(m.type, m.content) for m in first_state.values["messages"]] == [
        ("human", "Hi"),
        ("ai", "Nice to meet you!"),
        ("human", "How are you?"),
        ("ai", "Nice to meet you!"),
    ]
    second_state = await graph.aget_state(thread(second))
    assert len(second_state.values["messages"]) == 2


async def test_system_prompt_is_sent_but_not_stored(
    graph: ChatGraph, providers: TenantProviderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = RecordingChatModel()
    use_model(monkeypatch, model)
    thread_id = uuid.uuid4()

    await graph.ainvoke(
        {"messages": [HumanMessage("Hi")]}, thread(thread_id), context=ChatContext(providers)
    )

    [sent] = model.seen
    assert sent[0].type == "system" and "English tutor" in str(sent[0].content)
    stored = (await graph.aget_state(thread(thread_id))).values["messages"]
    assert all(m.type != "system" for m in stored)


async def test_tokens_stream_from_the_tutor_node(
    graph: ChatGraph, providers: TenantProviderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_model(monkeypatch, GenericFakeChatModel(messages=iter([AIMessage("Hello there friend")])))

    chunks: list[tuple[str, str]] = []
    async for chunk, metadata in graph.astream(
        {"messages": [HumanMessage("Hi")]},
        thread(uuid.uuid4()),
        context=ChatContext(providers),
        stream_mode="messages",
    ):
        # astream's return type covers every stream_mode; "messages" yields (chunk, dict).
        assert isinstance(chunk, AIMessageChunk) and isinstance(metadata, dict)
        chunks.append((metadata["langgraph_node"], str(chunk.content)))

    assert {node for node, _ in chunks} == {TUTOR_NODE}
    assert "".join(text for _, text in chunks) == "Hello there friend"


MEMORY_MARKER = "learner-memory-marker-that-must-not-be-persisted-7"


class FakeLearner:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.queries: list[str] = []

    async def load(self, query: str) -> LearnerContext:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("database down")
        return LearnerContext(profile={"Occupation": "nurse"}, facts=[MEMORY_MARKER])


async def test_learner_context_is_sent_but_never_checkpointed(
    graph: ChatGraph,
    providers: TenantProviderContext,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    model = RecordingChatModel()
    use_model(monkeypatch, model)
    learner = FakeLearner()
    thread_id = uuid.uuid4()
    context = ChatContext(providers, learner=learner)

    await graph.ainvoke({"messages": [HumanMessage("Hi")]}, thread(thread_id), context=context)
    await graph.ainvoke({"messages": [HumanMessage("Again")]}, thread(thread_id), context=context)

    assert learner.queries == ["Hi", "Again"]  # the latest message picks related episodes
    for sent in model.seen:
        assert MEMORY_MARKER in str(sent[0].content) and "Occupation: nurse" in str(sent[0].content)
    state = await graph.aget_state(thread(thread_id))
    assert set(state.values) == {"messages"}
    everything = await dump_checkpoints(db_session, thread_id)
    assert MEMORY_MARKER not in everything
    assert MEMORY_MARKER.encode().hex() not in everything


async def test_learner_context_failure_does_not_stop_the_reply(
    graph: ChatGraph, providers: TenantProviderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = RecordingChatModel()
    use_model(monkeypatch, model)

    result = await graph.ainvoke(
        {"messages": [HumanMessage("Hi")]},
        thread(uuid.uuid4()),
        context=ChatContext(providers, learner=FakeLearner(fail=True)),
    )

    assert result["messages"][-1].content == "Nice to meet you!"
    [sent] = model.seen
    assert "About this learner" not in str(sent[0].content)


class FakeActivity:
    turn_id = "turn-1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.steps: list[Step] = []

    async def record(self, step: Step) -> None:
        self.steps.append(step)
        if self.fail:
            raise RuntimeError("database down")


class LongMemories:
    """Three facts, of which only the first two fit the prompt's budget."""

    ids: ClassVar = [uuid.uuid4() for _ in range(3)]
    episode = uuid.uuid4()

    async def load(self, query: str) -> LearnerContext:
        fact = "x" * (MAX_FACTS_CHARS // 2)
        return LearnerContext(
            profile={"Occupation": "nurse", "Goal": "IELTS"},
            facts=[fact] * 3,
            episodes=["We talked about travel."],
            fact_ids=self.ids,
            episode_ids=[self.episode],
        )


async def test_reading_memories_is_recorded_and_streamed(
    graph: ChatGraph, providers: TenantProviderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_model(monkeypatch, RecordingChatModel())
    activity = FakeActivity()
    context = ChatContext(providers, learner=LongMemories(), activity=activity)

    custom = [
        part
        async for mode, part in graph.astream(
            {"messages": [HumanMessage("Hi")]},
            thread(uuid.uuid4()),
            context=context,
            stream_mode=["custom"],
        )
    ]

    [step] = activity.steps
    # Only the facts that made it into the prompt count as read.
    assert step.summary == ContextRead(
        facts=LongMemories.ids[:2], episodes=[LongMemories.episode], profile_items=2
    )
    assert step.status == "ok" and step.duration_ms is not None
    assert custom == [{"activity": step.payload("turn-1")}]


async def test_failed_memory_read_is_recorded_as_failed(
    graph: ChatGraph, providers: TenantProviderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_model(monkeypatch, RecordingChatModel())
    activity = FakeActivity()

    await graph.ainvoke(
        {"messages": [HumanMessage("Hi")]},
        thread(uuid.uuid4()),
        context=ChatContext(providers, learner=FakeLearner(fail=True), activity=activity),
    )

    [step] = activity.steps
    assert (step.status, step.summary) == ("failed", None)


async def test_failing_activity_record_does_not_stop_the_reply(
    graph: ChatGraph, providers: TenantProviderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_model(monkeypatch, RecordingChatModel())

    result = await graph.ainvoke(
        {"messages": [HumanMessage("Hi")]},
        thread(uuid.uuid4()),
        context=ChatContext(providers, learner=FakeLearner(), activity=FakeActivity(fail=True)),
    )

    assert result["messages"][-1].content == "Nice to meet you!"


PRACTICE_MARKER = "I goed practice-marker-7 yesterday"


class FakePractice:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def load(self) -> PracticeFocus:
        if self.fail:
            raise RuntimeError("database down")
        kc = get_grammar_catalog().get("g.word_order_svo")
        assert kc is not None
        return PracticeFocus(kc, "weak", [Mistake(PRACTICE_MARKER, "I went yesterday")])


async def test_practice_guidance_is_sent_but_never_checkpointed(
    graph: ChatGraph,
    providers: TenantProviderContext,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    model = RecordingChatModel()
    use_model(monkeypatch, model)
    thread_id = uuid.uuid4()
    context = ChatContext(providers, learner=FakeLearner(), practice=FakePractice())

    await graph.ainvoke({"messages": [HumanMessage("Hi")]}, thread(thread_id), context=context)

    [sent] = model.seen
    prompt = str(sent[0].content)
    # Practice comes last, after what the tutor knows about the learner.
    assert prompt.index("About this learner") < prompt.index("grammar practice")
    assert "Basic sentence structure" in prompt
    assert "current grasp: weak" in prompt
    assert f'"{PRACTICE_MARKER}" -> "I went yesterday"' in prompt
    assert set((await graph.aget_state(thread(thread_id))).values) == {"messages"}
    assert PRACTICE_MARKER not in await dump_checkpoints(db_session, thread_id)


async def test_free_chat_gets_no_practice_guidance(
    graph: ChatGraph, providers: TenantProviderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = RecordingChatModel()
    use_model(monkeypatch, model)

    await graph.ainvoke(
        {"messages": [HumanMessage("Hi")]},
        thread(uuid.uuid4()),
        context=ChatContext(providers, learner=FakeLearner()),
    )

    assert "grammar practice" not in str(model.seen[0][0].content)


async def test_practice_is_recorded_and_its_failure_does_not_stop_the_reply(
    graph: ChatGraph, providers: TenantProviderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = RecordingChatModel()
    use_model(monkeypatch, model)
    ok, broken = FakeActivity(), FakeActivity()

    await graph.ainvoke(
        {"messages": [HumanMessage("Hi")]},
        thread(uuid.uuid4()),
        context=ChatContext(providers, practice=FakePractice(), activity=ok),
    )
    result = await graph.ainvoke(
        {"messages": [HumanMessage("Hi")]},
        thread(uuid.uuid4()),
        context=ChatContext(
            providers, learner=FakeLearner(), practice=FakePractice(fail=True), activity=broken
        ),
    )

    [step] = ok.steps
    assert step.summary == ContextRead(practice_kc="g.word_order_svo")
    # The memories still arrived, so the step is not a failure; the reply goes out.
    [step] = broken.steps
    assert step.status == "ok"
    assert step.summary == ContextRead(profile_items=1)
    assert result["messages"][-1].content == "Nice to meet you!"
    assert "grammar practice" not in str(model.seen[-1][0].content)


async def dump_checkpoints(session: AsyncSession, thread_id: uuid.UUID) -> str:
    """Every row LangGraph persisted for the thread, as text (blobs decoded)."""
    dumped: list[str] = []
    for table in CHECKPOINT_TABLES:
        rows = await session.execute(
            text(f"SELECT t::text FROM {table} t WHERE thread_id = :tid"), {"tid": str(thread_id)}
        )
        dumped.extend(row[0] for row in rows)
    assert dumped, "expected checkpoint rows for the thread"
    blobs = await session.execute(
        text(
            "SELECT blob FROM checkpoint_blobs WHERE thread_id = :tid AND blob IS NOT NULL "
            "UNION ALL SELECT blob FROM checkpoint_writes WHERE thread_id = :tid"
        ),
        {"tid": str(thread_id)},
    )
    dumped.extend(bytes(row[0]).decode("utf-8", "replace") for row in blobs)
    return "\n".join(dumped)


async def test_provider_keys_never_reach_the_checkpoint(
    graph: ChatGraph,
    providers: TenantProviderContext,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    contexts = use_model(monkeypatch, RecordingChatModel())
    thread_id = uuid.uuid4()
    config = thread(thread_id)
    config["metadata"] = {"user_id": str(uuid.uuid4())}

    await graph.ainvoke({"messages": [HumanMessage("Hi")]}, config, context=ChatContext(providers))

    # The decrypted key really was in play for this run...
    [used] = contexts
    api_key = used.connections["openai"].api_key
    assert api_key is not None and api_key.get_secret_value() == KEY_MARKER
    # ...and nothing LangGraph persisted contains it (rows dumped as text, blobs decoded).
    everything = await dump_checkpoints(db_session, thread_id)
    assert KEY_MARKER not in everything
    assert KEY_MARKER.encode().hex() not in everything  # bytea renders as \x<hex>
