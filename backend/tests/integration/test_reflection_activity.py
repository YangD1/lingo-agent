"""What reflection records for the learner to see (ADR 0013 §3)."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity import service as activity
from app.activity.service import GrammarMistake, GrammarTags, MemoryChanges, SummaryUpdate
from app.db.models import AgentActivity
from app.memory import reflection, service
from app.memory.reflection import MemoryOp, Reflection, TaggedMistake, UsedCorrectly
from app.memory.worker import SUMMARY_EVERY_TURNS
from app.providers.errors import NoModelConfiguredError
from tests.integration.test_chat_send import connect, history, login, new_conversation, send
from tests.integration.test_reflection import FakeReflector, idle, learner, reflector  # noqa: F401

KC = "g.present_simple_third_person"


async def rows(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: str
) -> list[AgentActivity]:
    session.expire_all()
    return list(await activity.list_activities(session, user_id, uuid.UUID(conversation_id)))


def by_name(found: list[AgentActivity], name: str) -> list[AgentActivity]:
    return [r for r in found if r.name == name]


async def test_memory_changes_and_grammar_tags_are_recorded(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
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
            used_correctly=[UsedCorrectly(message="u1", kc_id="g.present_continuous")],
        )
    )
    user, _ = await learner(db_session)

    await send(client, conversation_id, "She like music and she is playing now.")
    await idle(app)

    turn = (await history(client, conversation_id))[0]["id"]
    user_id = user.id
    found = await rows(db_session, user_id, conversation_id)
    assert [(r.turn_id, r.name, r.status) for r in found] == [
        (turn, "load_context", "ok"),
        (turn, "reflect_memory", "ok"),
        (turn, "grammar_tagging", "ok"),
    ]
    [fact] = await service.list_memories(db_session, user_id, "fact")
    assert activity.parse_summary(found[1]) == MemoryChanges(added=[fact.id])
    assert activity.parse_summary(found[2]) == GrammarTags(
        mistakes=[
            GrammarMistake(
                kc_id=KC,
                error_type="omission",
                severity="medium",
                original="She like",
                correction="She likes",
            )
        ],
        used_correctly=["g.present_continuous"],
    )
    assert found[1].duration_ms is not None


async def test_a_batch_files_memory_under_its_last_turn_and_tags_under_each(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    app.state.reflection_worker.enabled = False  # the first turn waits for the second
    await send(client, conversation_id, "First")
    app.state.reflection_worker.enabled = True
    await send(client, conversation_id, "Second")
    await idle(app)
    user, _ = await learner(db_session)

    first, _, second, _ = [m["id"] for m in await history(client, conversation_id)]
    found = await rows(db_session, user.id, conversation_id)
    assert [r.turn_id for r in by_name(found, "reflect_memory")] == [second]
    assert [r.turn_id for r in by_name(found, "grammar_tagging")] == [first, second]


async def test_failed_reflection_is_shown_as_failed(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    reflector.failures = 2

    await send(client, conversation_id, "Hello")
    await idle(app)

    user, _ = await learner(db_session)
    found = await rows(db_session, user.id, conversation_id)
    background = [(r.name, r.status, r.summary) for r in found if r.kind == "background"]
    assert background == [("reflect_memory", "failed", {}), ("grammar_tagging", "failed", {})]


async def test_without_a_reflection_model_it_is_shown_as_skipped(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unconfigured(ctx: Any, task: str, schema: type[BaseModel]) -> Any:
        raise NoModelConfiguredError("llm", task, [])

    monkeypatch.setattr(reflection, "get_structured_llm", unconfigured)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)

    await send(client, conversation_id, "Hello")
    await idle(app)

    user, _ = await learner(db_session)
    found = await rows(db_session, user.id, conversation_id)
    assert {r.status for r in found if r.kind == "background"} == {"skipped"}


async def test_rewritten_summary_is_recorded_on_the_last_turn(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    for i in range(SUMMARY_EVERY_TURNS):
        await send(client, conversation_id, f"Turn {i}")
        await idle(app)

    user, _ = await learner(db_session)
    user_id = user.id
    [episode] = await service.list_memories(db_session, user_id, "episode")
    episode_id = episode.id
    last_turn = (await history(client, conversation_id))[-2]["id"]
    [row] = by_name(await rows(db_session, user_id, conversation_id), "summarize")
    assert row.turn_id == last_turn
    assert activity.parse_summary(row) == SummaryUpdate(episode_id=episode_id)
