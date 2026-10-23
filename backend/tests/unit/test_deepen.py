"""When the tutor's follow-ups are written and how their limits stop them (ADR 0064)."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.chat_graph import build_chat_graph
from app.agents.deepen import (
    CONTINUE_DEEPER,
    OUTCOME_KEY,
    SEGMENT_KEY,
    offer,
    rough_tokens,
    rule_fires,
    trigger,
    turn_state,
    write_segment,
)
from app.chat.deepen import DeepenSettings
from app.chat.service import thread_config
from app.chat.turn import SegmentEvent, TokenEvent, stream_reply
from app.providers import llm
from tests.unit.provider_fixtures import conn, make_ctx

ON = DeepenSettings()


def fast(**limits: float) -> DeepenSettings:
    """Limits below the API's bounds, so the tests don't wait seconds."""
    return DeepenSettings.model_construct(**{**ON.model_dump(), **limits})


@pytest.mark.parametrize(
    ("text", "fires"),
    [
        ("Why do we say 'I have been' here?", True),
        ("affect 和 effect 有什么区别", True),
        ("为什么这里用现在完成时", True),
        ("What's the difference between say and tell?", True),
        ("Hi, how are you today?", False),
        ("Thanks!", False),
        ("Can you explain the present perfect?", False),
        # Long questions, in either language.
        (
            "How should I use the present perfect when I talk about things that happened "
            "at an unknown time?",
            True,
        ),
        ("我想知道在写邮件的时候应该怎样礼貌地拒绝别人的邀请才不会显得生硬和不礼貌呢", True),
        # Long, but not a question.
        (
            "I went to the park yesterday with my friends and we played football until "
            "it got dark outside.",
            False,
        ),
    ],
)
def test_rules(text: str, fires: bool) -> None:
    assert rule_fires(text) is fires


def ask_deeper(text: str = "Short.") -> AIMessage:
    call = {"name": CONTINUE_DEEPER, "args": {"reason": "contrast with past simple"}, "id": "c1"}
    return AIMessage(text, tool_calls=[call])


def segment(index: int = 1, *, more: bool = False) -> AIMessage:
    calls = [{"name": CONTINUE_DEEPER, "args": {"reason": "x"}, "id": f"s{index}"}] if more else []
    return AIMessage(
        "Deeper.", tool_calls=calls, additional_kwargs={SEGMENT_KEY: index, OUTCOME_KEY: "done"}
    )


def test_an_opening_or_no_settings_gets_none() -> None:
    assert trigger(turn_state([AIMessage("Hello!")]), ON) is None
    asked = turn_state([HumanMessage("Why?"), AIMessage("Because.")])
    assert trigger(asked, None) is None
    assert trigger(asked, DeepenSettings(enabled=False)) is None
    assert offer(asked, DeepenSettings(enabled=False)) is None


def test_a_rule_or_the_tutor_starts_one() -> None:
    by_rule = turn_state([HumanMessage("Why is it 'has gone'?"), AIMessage("Short.")])
    assert (trigger(by_rule, ON), offer(by_rule, ON)) == ("rule", "coming")

    asked = turn_state([HumanMessage("Explain it please"), ask_deeper()])
    assert (trigger(asked, ON), asked.asked) == ("model", "contrast with past simple")
    assert offer(asked, ON) == "coming"  # a later call this turn is told it is coming

    plain = turn_state([HumanMessage("Explain it please"), AIMessage("Short.")])
    assert (trigger(plain, ON), offer(plain, ON)) == (None, "tool")


def test_segments_stop_at_the_limit_and_need_asking_for() -> None:
    one = [HumanMessage("Why?"), AIMessage("Short."), segment(1)]
    assert trigger(turn_state(one), ON) is None  # max_segments 1
    assert trigger(turn_state(one), DeepenSettings(max_segments=2)) is None  # not asked
    more = [HumanMessage("Why?"), AIMessage("Short."), segment(1, more=True)]
    assert trigger(turn_state(more), DeepenSettings(max_segments=2)) == "model"
    two = [*more, segment(2, more=True)]
    assert trigger(turn_state(two), DeepenSettings(max_segments=2)) is None


def test_after_follow_ups_in_two_of_three_turns_only_rules_start_one() -> None:
    def turn(text: str, deepened: bool) -> list[BaseMessage]:
        return [HumanMessage(text), AIMessage("Short."), *([segment()] if deepened else [])]

    earlier = [*turn("a", True), *turn("b", False), *turn("c", True)]
    asked = turn_state([*earlier, HumanMessage("Explain it please"), ask_deeper()])
    assert not asked.model_allowed
    assert trigger(asked, ON) is None
    assert offer(turn_state([*earlier, HumanMessage("Explain it please")]), ON) is None
    by_rule = turn_state([*earlier, HumanMessage("Why?"), AIMessage("Short.")])
    assert trigger(by_rule, ON) == "rule"
    # Four turns back no longer counts.
    older = [*turn("a", True), *turn("b", False), *turn("c", False), *turn("d", True)]
    assert turn_state([*older, HumanMessage("Explain"), ask_deeper()]).model_allowed


def test_rough_tokens() -> None:
    assert rough_tokens("") == 0
    assert rough_tokens("abcd" * 10) == 10
    assert rough_tokens("现在完成时") == 5


class Scripted(BaseChatModel):
    """Streams the given chunks; a float is a pause, an exception is raised."""

    steps: Any

    @property
    def _llm_type(self) -> str:
        return "scripted"

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
        for step in self.steps:
            if isinstance(step, float):
                await asyncio.sleep(step)
            elif isinstance(step, Exception):
                raise step
            else:
                yield ChatGenerationChunk(message=step)


def text(value: str) -> AIMessageChunk:
    return AIMessageChunk(content=value, id="seg")


async def write(steps: list[Any], settings: DeepenSettings) -> Any:
    return await write_segment(Scripted(steps=steps), [HumanMessage("hi")], {}, settings, 1)


async def test_a_finished_follow_up_is_kept_without_its_thinking() -> None:
    thinking = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "hmm"})
    done = await write([thinking, text("One. "), text("Two.")], ON)
    assert done.outcome == "done"
    assert done.message.text == "One. Two."
    assert done.message.additional_kwargs == {SEGMENT_KEY: 1, OUTCOME_KEY: "done"}


async def test_nothing_in_time_is_no_start_and_keeps_nothing() -> None:
    late = await write([0.5, text("Too late.")], fast(first_chunk_seconds=0.05))
    assert (late.outcome, late.message) == ("no_start", None)
    # An empty first chunk doesn't count as starting; thinking does.
    empty = await write(
        [AIMessageChunk(content=""), 0.5, text("x")], fast(first_chunk_seconds=0.05)
    )
    assert empty.outcome == "no_start"
    thinking = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "hmm"})
    thought = await write([thinking, 0.1, text("x")], fast(first_chunk_seconds=0.05))
    assert thought.outcome == "done"


async def test_the_time_and_length_limits_keep_what_was_written() -> None:
    slow = await write([text("Half "), 0.5, text("never")], fast(total_seconds=0.1))
    assert (slow.outcome, slow.message.text) == ("timeout", "Half")
    assert slow.message.additional_kwargs[OUTCOME_KEY] == "timeout"
    long = await write([text("abcd" * 5)] * 10, fast(max_tokens=12))
    assert long.outcome == "length"
    assert rough_tokens(long.message.text) < 20


async def test_a_failure_keeps_what_was_written() -> None:
    broken = await write([text("Part of it."), RuntimeError("vendor")], ON)
    assert (broken.outcome, broken.message.text) == ("failed", "Part of it.")
    nothing = await write([RuntimeError("vendor")], ON)
    assert (nothing.outcome, nothing.message) == ("failed", None)


# --- in the graph ------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    llm.reset_caches()
    yield
    llm.reset_caches()


async def test_stopping_a_follow_up_keeps_the_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 0064 §6: the reply is checkpointed before its follow-up starts, so a learner
    who stops the follow-up (to send a new message) keeps the reply."""
    models = {
        "chat": Scripted(steps=[AIMessageChunk(content="Short answer.")]),
        "chat_deep": Scripted(steps=[text("Deeper "), 30.0]),
    }
    monkeypatch.setattr(llm, "get_chat_models", lambda ctx, task: (models[task],))
    graph = build_chat_graph(InMemorySaver())
    conversation = uuid.uuid4()
    events = stream_reply(
        graph,
        conversation_id=conversation,
        user_id=uuid.uuid4(),
        providers=make_ctx(conn("openai")),
        text="Why is it 'has gone'?",
        message_id=str(uuid.uuid4()),
        deepen=ON,
    )
    seen: list[Any] = []
    async for event in events:
        seen.append(event)
        if isinstance(event, TokenEvent) and event.text == "Deeper ":
            break
    await events.aclose()  # type: ignore[attr-defined]  # an async generator

    assert SegmentEvent(index=1, state="started") in seen
    state = await graph.aget_state(thread_config(conversation))
    stored = state.values["messages"]
    assert [m.text for m in stored] == ["Why is it 'has gone'?", "Short answer."]
