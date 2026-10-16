"""A streamed call's token usage is counted once (task 93).

SiliconFlow puts the running total on every chunk; langchain used to add them up, so a
17k-token answer was recorded as 141M. The vendor here speaks real SSE to the real
OpenAI client.
"""

import json
import uuid
from typing import Any, TypedDict

import httpx2
from langchain_core.messages import AIMessageChunk, BaseMessage
from langgraph.graph import END, START, StateGraph
from pydantic import SecretStr

from app.providers.clients import UsageOnceChatOpenAI
from app.providers.config import ResolvedModel
from app.providers.llm import build_chat_model
from app.usage.recorder import UsageLabels, UsageRecord, UsageRecorder

BASE = "https://api.siliconflow.cn/v1"
WORDS = ["The", " cat", " sat", " down", "."]


def usage(prompt: int, completion: int) -> dict[str, int]:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def chunk(content: str | None, *, finish: str | None = None, **extra: Any) -> dict[str, Any]:
    choices = [] if content is None else [{"index": 0, "delta": {"content": content}}]
    if choices and finish:
        choices[0]["finish_reason"] = finish
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "model": "m",
        "choices": choices,
        **extra,
    }


def running_totals() -> list[dict[str, Any]]:
    """SiliconFlow: every chunk carries the usage so far."""
    last = len(WORDS) - 1
    return [
        chunk(w, finish="stop" if i == last else None, usage=usage(40, i + 1))
        for i, w in enumerate(WORDS)
    ]


def at_the_end() -> list[dict[str, Any]]:
    """OpenAI: one extra chunk with no choices carries the usage."""
    return [chunk(w) for w in WORDS] + [chunk(None, usage=usage(40, 5))]


def split() -> list[dict[str, Any]]:
    """Input on the first chunk, output on the last."""
    first, *rest = WORDS
    return [
        chunk(first, usage={"prompt_tokens": 40}),
        *(chunk(w) for w in rest),
        chunk(None, usage={"completion_tokens": 5}),
    ]


def vendor(chunks: list[dict[str, Any]]) -> httpx2.MockTransport:
    def handle(request: httpx2.Request) -> httpx2.Response:
        body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx2.Response(
            200, content=body.encode(), headers={"content-type": "text/event-stream"}
        )

    return httpx2.MockTransport(handle)


def model(chunks: list[dict[str, Any]], **kwargs: Any) -> UsageOnceChatOpenAI:
    return UsageOnceChatOpenAI(
        model="deepseek-ai/DeepSeek-V4.1-Flash",
        api_key=SecretStr("sk-test"),
        base_url=BASE,
        max_retries=0,
        stream_usage=True,
        http_async_client=httpx2.AsyncClient(transport=vendor(chunks)),
        **kwargs,
    )


async def streamed_usage(chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    total: AIMessageChunk | None = None
    async for part in model(chunks).astream("hi"):
        total = part if total is None else total + part
    assert total is not None
    assert total.text == "The cat sat down."
    return dict(total.usage_metadata) if total.usage_metadata else None


async def test_running_totals_are_counted_once() -> None:
    got = await streamed_usage(running_totals())
    assert got is not None
    assert (got["input_tokens"], got["output_tokens"], got["total_tokens"]) == (40, 5, 45)


async def test_usage_on_the_last_chunk_is_unchanged() -> None:
    got = await streamed_usage(at_the_end())
    assert got is not None
    assert (got["input_tokens"], got["output_tokens"], got["total_tokens"]) == (40, 5, 45)


async def test_input_and_output_in_separate_chunks_both_count() -> None:
    got = await streamed_usage(split())
    assert got is not None
    assert (got["input_tokens"], got["output_tokens"]) == (40, 5)


async def test_the_recorder_gets_the_real_total() -> None:
    """What lands in llm_usage: the exercise pipeline streams, then reads on_llm_end."""
    records: list[UsageRecord] = []
    labels = UsageLabels(
        tenant_id=uuid.uuid4(), task="exercise_generate", connection="sf", model="m"
    )
    recorder = UsageRecorder(labels, records.append)
    async for _ in model(running_totals()).astream("hi", config={"callbacks": [recorder]}):
        pass
    assert [(r.input_tokens, r.output_tokens) for r in records] == [(40, 5)]


async def test_a_streamed_chat_reply_adds_up_to_the_real_total() -> None:
    """chat/turn.py adds up the usage of the chunks a graph streams as messages."""

    class State(TypedDict):
        messages: list[BaseMessage]

    chat = model(running_totals())

    async def reply(state: State) -> State:
        return {"messages": [await chat.ainvoke("hi")]}

    graph = StateGraph(State).add_node("tutor", reply)
    graph.add_edge(START, "tutor").add_edge("tutor", END)
    seen = [0, 0]
    async for part, _ in graph.compile().astream({"messages": []}, stream_mode="messages"):
        if isinstance(part, AIMessageChunk) and part.usage_metadata:
            seen[0] += part.usage_metadata["input_tokens"]
            seen[1] += part.usage_metadata["output_tokens"]
    assert seen == [40, 5]


def test_openai_compatible_connections_get_it() -> None:
    resolved = ResolvedModel("sf", "openai_compatible", "Qwen/Qwen3-8B", BASE, None, {})
    assert isinstance(build_chat_model(resolved, "chat"), UsageOnceChatOpenAI)
