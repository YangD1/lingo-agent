import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import anyio
import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.chat_graph import build_chat_graph
from app.chat.turn import TokenEvent, TurnEvent, stream_reply, title_from
from app.providers import llm
from app.usage.recorder import UsageLabels, UsageRecord, UsageRecorder
from tests.unit.provider_fixtures import TENANT, conn, make_ctx


class SlowChatModel(BaseChatModel):
    """Streams 10 chunks, 0.1s apart, and reports how the stream ended."""

    # Any: pydantic would copy a list[str] on validation, hiding the appends from tests.
    outcome: Any

    @property
    def _llm_type(self) -> str:
        return "slow"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        try:
            for i in range(10):
                await asyncio.sleep(0.1)
                yield ChatGenerationChunk(message=AIMessageChunk(content=f"w{i} "))
        except BaseException as exc:
            self.outcome.append(f"aborted:{type(exc).__name__}")
            raise
        self.outcome.append("completed")


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    llm.reset_caches()
    yield
    llm.reset_caches()


def turn(model: BaseChatModel, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[TurnEvent]:
    monkeypatch.setattr(llm, "get_chat_models", lambda ctx, task: (model,))
    return stream_reply(
        build_chat_graph(InMemorySaver()),
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        providers=make_ctx(conn("openai")),
        text="hi",
    )


async def test_disconnect_under_anyio_cancellation_stops_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client disconnect cancels the SSE producer through an anyio cancel scope.

    That cancellation is level-triggered, which also cancels LangGraph's own cleanup
    awaits and would leave the node task running (and the provider billing) unless
    the graph runs in its own task that we cancel explicitly.
    """
    outcome: list[str] = []
    received: list[TurnEvent] = []
    records: list[UsageRecord] = []
    recorder = UsageRecorder(UsageLabels(TENANT, "chat", "openai", "m"), records.append)

    with anyio.move_on_after(0.35):
        async for event in turn(SlowChatModel(outcome=outcome, callbacks=[recorder]), monkeypatch):
            received.append(event)

    assert 1 <= len(received) < 10 and all(isinstance(e, TokenEvent) for e in received)
    # Cancellation reached the model right away, not after the stream ran out.
    assert outcome == ["aborted:CancelledError"]
    await asyncio.sleep(1.2)  # long enough for an orphaned stream to finish
    assert outcome == ["aborted:CancelledError"]
    # The provider billed for the partial reply, so the call must still be metered.
    assert [(r.status, r.error_code) for r in records] == [("error", "CancelledError")]


async def test_completed_turn_ends_with_done(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome: list[str] = []

    events = [e async for e in turn(SlowChatModel(outcome=outcome), monkeypatch)]

    assert outcome == ["completed"]
    assert [e.event for e in events] == ["token"] * 10 + ["done"]


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ("Hello", "Hello"),
        (
            "  Could you   help me practise\n job interview questions?",
            "Could you help me practise job interview",
        ),
        ("x" * 100, "x" * 40),
    ],
)
def test_title_from(text: str, title: str) -> None:
    assert title_from(text) == title
