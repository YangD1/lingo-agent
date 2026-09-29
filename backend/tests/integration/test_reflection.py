"""Post-turn reflection through the real send-message endpoint (ADR 0009 §3)."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, TenantMember, User
from app.memory import reflection, service
from app.memory.reflection import EpisodeSummary, KnownFact, MemoryOp, ProfileUpdate, Reflection
from app.memory.worker import SUMMARY_EVERY_TURNS, ReflectionWorker
from tests.integration.test_chat_send import (
    connect,
    fake_models,
    login,
    new_conversation,
    send,
)


class FakeReflector:
    """Stands in for the `reflect` route: canned results, and what it was asked."""

    def __init__(self) -> None:
        self.reflections: list[Reflection] = []
        self.prompts: list[str] = []
        self.summary_prompts: list[str] = []
        self.configs: list[RunnableConfig | None] = []
        self.failures = 0

    def get_structured_llm(
        self, ctx: Any, task: str, schema: type[BaseModel]
    ) -> Runnable[Any, Any]:
        assert task == "reflect"

        async def run(messages: list[BaseMessage], config: RunnableConfig | None = None) -> Any:
            self.configs.append(config)
            if self.failures:
                self.failures -= 1
                raise RuntimeError("model glitch")
            prompt = str(messages[-1].content)
            if schema is EpisodeSummary:
                self.summary_prompts.append(prompt)
                return EpisodeSummary(summary=f"Summary {len(self.summary_prompts)}")
            self.prompts.append(prompt)
            return self.reflections.pop(0) if self.reflections else Reflection()

        return RunnableLambda(run)


@pytest.fixture
def reflector(monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> Iterator[FakeReflector]:
    fake = FakeReflector()
    monkeypatch.setattr(reflection, "get_structured_llm", fake.get_structured_llm)
    fake_models(monkeypatch)  # the tutor's streamed replies
    worker: ReflectionWorker = app.state.reflection_worker
    worker.enabled = True
    yield fake


async def learner(session: AsyncSession) -> tuple[User, uuid.UUID]:
    user = await session.scalar(select(User).where(User.email == "learner@example.com"))
    assert user is not None
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user.id)
    )
    assert tenant_id is not None
    return user, tenant_id


async def idle(app: FastAPI) -> None:
    await app.state.reflection_worker.wait_idle()


async def test_reply_is_followed_by_reflection_that_remembers(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, reflector: FakeReflector
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    reflector.reflections.append(
        Reflection(
            memory_ops=[MemoryOp(action="add", content="Works as a backend developer.")],
            profile_updates=ProfileUpdate(occupation="backend developer", target_exam="ielts"),
        )
    )
    client.cookies.set("NEXT_LOCALE", "zh-CN")
    user, _ = await learner(db_session)

    status, events, _ = await send(client, conversation_id, "I'm a backend developer.")
    assert status == 200 and events[-1][0] == "done"
    await idle(app)

    [prompt] = reflector.prompts
    assert "Write facts in: Simplified Chinese" in prompt
    assert "Learner: I'm a backend developer." in prompt.split("## New messages")[1]
    facts = await service.list_memories(db_session, user.id, "fact")
    assert [f.content for f in facts] == ["Works as a backend developer."]
    assert facts[0].source_conversation_id == uuid.UUID(conversation_id)
    profile = await service.get_profile(db_session, user.id)
    assert profile is not None and (profile.occupation, profile.target_exam) == (
        "backend developer",
        "ielts",
    )
    assert profile.manual_fields == []
    # Calls are attributed to the learner and conversation (llm_usage reads these).
    config = reflector.configs[0]
    assert config is not None and config["metadata"] == {
        "user_id": str(user.id),
        "conversation_id": conversation_id,
    }
    db_session.expire_all()
    conversation = await db_session.get(Conversation, uuid.UUID(conversation_id))
    assert conversation is not None and conversation.reflected_message_id is not None

    # The next turn reflects on the new messages only; the earlier ones are context.
    await send(client, conversation_id, "I also like hiking.")
    await idle(app)
    new_part = reflector.prompts[1].split("## New messages")[1]
    assert "hiking" in new_part and "backend developer." not in new_part
    assert "m1: Works as a backend developer." in reflector.prompts[1]


async def test_reflection_does_not_move_the_conversation_in_the_list(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, reflector: FakeReflector
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    worker: ReflectionWorker = app.state.reflection_worker
    worker.enabled = False
    await send(client, conversation_id, "Hello")
    stamp = await db_session.scalar(
        select(Conversation.updated_at).where(Conversation.id == uuid.UUID(conversation_id))
    )
    worker.enabled = True
    worker.schedule(uuid.UUID(conversation_id), finish=True)  # moves both cursors
    await idle(app)
    assert reflector.prompts and reflector.summary_prompts
    db_session.expire_all()
    after = await db_session.scalar(
        select(Conversation.updated_at).where(Conversation.id == uuid.UUID(conversation_id))
    )
    assert after == stamp


async def test_failures_are_retried_once_then_the_turn_is_skipped(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, reflector: FakeReflector
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    reflector.failures = 2
    reflector.reflections.append(
        Reflection(memory_ops=[MemoryOp(action="add", content="Never stored.")])
    )

    status, events, _ = await send(client, conversation_id, "Hello")
    await idle(app)

    assert status == 200 and events[-1][0] == "done"
    user, _ = await learner(db_session)
    assert await service.list_memories(db_session, user.id) == []
    # Not retried forever: the next turn starts after it.
    await send(client, conversation_id, "Second")
    await idle(app)
    [prompt] = reflector.prompts
    assert "Hello" not in prompt.split("## New messages")[1]


async def test_summary_every_few_turns_and_when_the_learner_moves_on(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, reflector: FakeReflector
) -> None:
    await login(client)
    await connect(client, "deepseek")
    first = await new_conversation(client)
    for i in range(SUMMARY_EVERY_TURNS):
        await send(client, first, f"Turn {i}")
        await idle(app)
    user, _ = await learner(db_session)
    user_id = user.id
    [episode] = await service.list_memories(db_session, user_id, "episode")
    assert episode.content == "Summary 1"
    assert "Turn 0" in reflector.summary_prompts[0]

    # Two more turns: not enough for a new summary...
    await send(client, first, "Turn 6")
    await send(client, first, "Turn 7")
    await idle(app)
    assert len(reflector.summary_prompts) == 1
    # ...until the learner starts another conversation: then the rest is folded in.
    await new_conversation(client)
    await idle(app)
    [prompt] = reflector.summary_prompts[1:]
    assert "## Previous summary\nSummary 1" in prompt
    assert "Turn 7" in prompt and "Turn 0" not in prompt
    db_session.expire_all()
    [episode] = await service.list_memories(db_session, user_id, "episode")
    assert episode.content == "Summary 2"


async def test_disabled_reflection_makes_no_calls(
    client: AsyncClient, app: FastAPI, reflector: FakeReflector
) -> None:
    app.state.reflection_worker.enabled = False
    await login(client)
    await connect(client, "deepseek")
    await send(client, await new_conversation(client), "Hello")
    await idle(app)
    assert reflector.configs == []


async def test_recover_picks_up_turns_missed_by_a_restart(
    client: AsyncClient, app: FastAPI, reflector: FakeReflector
) -> None:
    await login(client)
    await connect(client, "deepseek")
    app.state.reflection_worker.enabled = False  # as if the process died before reflecting
    await send(client, await new_conversation(client), "I work at a hospital.")
    app.state.reflection_worker.enabled = True

    assert await app.state.reflection_worker.recover() == 1
    await idle(app)
    assert "hospital" in reflector.prompts[0]


# --- applying a reflection ----------------------------------------------------------------


async def test_operations_only_touch_the_facts_the_model_was_shown(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    user, tenant_id = await learner(db_session)
    conversation = Conversation(tenant_id=tenant_id, user_id=user.id)
    db_session.add(conversation)
    await db_session.commit()
    rows = [
        await service.add_memory(
            db_session, tenant_id=tenant_id, user_id=user.id, kind="fact", content=text
        )
        for text in ("Lives in Shanghai.", "Likes jazz.", "Has a cat.")
    ]
    facts = [KnownFact(m.id, m.content) for m in rows]
    await service.update_profile(db_session, user.id, {"goal": "Pass IELTS"}, by_learner=True)

    applied = await reflection.apply_reflection(
        db_session,
        Reflection(
            memory_ops=[
                MemoryOp(action="update", id="m1", content="Lives in Berlin."),
                MemoryOp(action="delete", id="m2"),
                MemoryOp(action="delete", id="m1"),  # already touched this turn
                MemoryOp(action="delete", id="m9"),  # not shown: ignored
                MemoryOp(action="add", content="has a cat"),  # duplicate of m3
                MemoryOp(action="add", content="   "),  # empty
                *[MemoryOp(action="add", content=f"New fact {i}.") for i in range(8)],
            ],
            profile_updates=ProfileUpdate(goal="Travel", daily_minutes=30),
        ),
        tenant_id=tenant_id,
        user_id=user.id,
        conversation_id=conversation.id,
        facts=facts,
        embedder=None,
    )

    assert (applied.added, applied.updated, applied.deleted) == (5, 1, 1)
    contents = {m.content for m in await service.list_memories(db_session, user.id, "fact")}
    assert {"Lives in Berlin.", "Has a cat."} <= contents
    assert "Likes jazz." not in contents and len(contents) == 7
    profile = await service.get_profile(db_session, user.id)
    assert profile is not None and (profile.goal, profile.daily_minutes) == ("Pass IELTS", 30)
