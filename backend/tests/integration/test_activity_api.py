"""GET /conversations/{id}/activity (ADR 0013 §3)."""

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from app.memory import reflection
from app.memory.reflection import MemoryOp, Reflection, TaggedMistake
from tests.integration.test_chat_send import connect, history, login, new_conversation, send
from tests.integration.test_reflection import FakeReflector, idle, reflector  # noqa: F401

KC = "g.present_simple_third_person"


async def activity(client: AsyncClient, conversation_id: str, **params: Any) -> dict[str, Any]:
    response = await client.get(f"/conversations/{conversation_id}/activity", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_turns_come_with_the_memories_and_kcs_they_refer_to(
    client: AsyncClient,
    app: FastAPI,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    reflector.reflections.append(
        Reflection(
            memory_ops=[MemoryOp(action="add", content="Has a sister.")],
            mistakes=[
                TaggedMistake(
                    message="u1",
                    kc_id=KC,
                    error_type="omission",
                    severity="medium",
                    original="She like",
                    correction="She likes",
                )
            ],
        )
    )
    await send(client, conversation_id, "She like music.")
    await idle(app)
    reflector.reflections.append(Reflection())
    await send(client, conversation_id, "Thanks!")
    await idle(app)
    first, _, second, _ = [m["id"] for m in await history(client, conversation_id)]

    body = await activity(client, conversation_id, turn=first)

    assert [(a["turn_id"], a["name"]) for a in body["activities"]] == [
        (first, "load_context"),
        (first, "reflect_memory"),
        (first, "grammar_tagging"),
    ]
    [fact_id] = body["activities"][1]["summary"]["added"]
    assert body["memories"] == {fact_id: {"kind": "fact", "content": "Has a sister."}}
    assert body["kcs"][KC]["name_en"] and body["kcs"][KC]["cefr"] == "A1"
    assert body["pending"] is False
    # The second turn read the fact the first one wrote.
    second_turn = await activity(client, conversation_id, turn=second)
    assert second_turn["activities"][0]["summary"]["facts"] == [fact_id]

    # Deleted memories are no longer quoted; the activity itself stays.
    assert (await client.delete(f"/memories/{fact_id}")).status_code == 204
    body = await activity(client, conversation_id)
    assert body["memories"] == {} and len(body["activities"]) == 6


async def test_pending_while_reflection_runs(
    client: AsyncClient,
    app: FastAPI,
    reflector: FakeReflector,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    def slow(ctx: Any, task: str, schema: type[BaseModel]) -> Runnable[Any, Any]:
        async def run(messages: Any, config: Any = None) -> Reflection:
            await release.wait()
            return Reflection()

        return RunnableLambda(run)

    monkeypatch.setattr(reflection, "get_structured_llm", slow)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    await send(client, conversation_id, "Hello")

    assert (await activity(client, conversation_id))["pending"] is True
    release.set()
    await idle(app)
    body = await activity(client, conversation_id)
    assert body["pending"] is False
    assert [a["name"] for a in body["activities"]][-1] == "grammar_tagging"


async def test_someone_elses_conversation_is_not_found(
    client: AsyncClient,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    await login(client, "other@example.com")

    response = await client.get(f"/conversations/{conversation_id}/activity")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "conversation_not_found"
