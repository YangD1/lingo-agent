"""The tutor sees the learner's memories through the real send-message endpoint."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ExerciseSet, Memory, TenantMember, User
from app.memory import context as learner_context
from app.memory import service
from app.providers import llm
from app.providers.config import ResolvedModel
from tests.integration.test_chat_send import connect, login, new_conversation, send
from tests.integration.test_chat_tools import activity
from tests.integration.test_quiz_tools import KC, answer


class PromptRecorder(BaseChatModel):
    prompts: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "prompt-recorder"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("the chat graph always streams")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self.prompts.append(str(messages[0].content))
        yield ChatGenerationChunk(message=AIMessageChunk(content="Sure!"))


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> PromptRecorder:
    model = PromptRecorder()

    def build(
        resolved: ResolvedModel, task: str, *, callbacks: list[Any] | None = None
    ) -> BaseChatModel:
        return model

    monkeypatch.setattr(llm, "build_chat_model", build)
    return model


async def test_new_conversation_uses_memories_and_forgets_deleted_ones(
    client: AsyncClient, db_session: AsyncSession, recorder: PromptRecorder
) -> None:
    await login(client)
    await connect(client, "deepseek")  # no embedding model: retrieval by recency
    user = await db_session.scalar(select(User).where(User.email == "learner@example.com"))
    assert user is not None
    tenant_id = await db_session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user.id)
    )
    assert tenant_id is not None
    await service.update_profile(
        db_session, user.id, {"occupation": "backend developer"}, by_learner=True
    )
    fact = await service.add_memory(
        db_session,
        tenant_id=tenant_id,
        user_id=user.id,
        kind="fact",
        content="Has a job interview next month",
    )

    status, events, _ = await send(client, await new_conversation(client), "Help me practise")
    assert status == 200 and events[-1][0] == "done"
    assert "Occupation: backend developer" in recorder.prompts[-1]
    assert "Has a job interview next month" in recorder.prompts[-1]

    await service.delete_memory(db_session, user.id, fact.id)
    await send(client, await new_conversation(client), "Help me practise")
    assert "job interview" not in recorder.prompts[-1]


async def test_facts_reflection_adds_wait_for_the_next_sitting(
    client: AsyncClient, db_session: AsyncSession, recorder: PromptRecorder
) -> None:
    """ADR 0053 §3: the prompt prefix stays put within a sitting, but what the learner
    deletes or adds on the memory page applies at once."""
    await login(client)
    await connect(client, "deepseek")
    user = await db_session.scalar(select(User).where(User.email == "learner@example.com"))
    assert user is not None
    tenant_id = await db_session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user.id)
    )
    assert tenant_id is not None
    conversation = await new_conversation(client)
    conversation_id = uuid.UUID(conversation)

    async def remember(content: str, *, by_reflection: bool) -> Memory:
        # created_at is now() of the transaction: end the one the last refresh opened.
        await db_session.commit()
        return await service.add_memory(
            db_session,
            tenant_id=tenant_id,
            user_id=user.id,
            kind="fact",
            content=content,
            source_conversation_id=conversation_id if by_reflection else None,
        )

    old = await remember("Has a job interview next month", by_reflection=True)
    await send(client, conversation, "Hi")
    assert "job interview" in recorder.prompts[-1]

    await remember("Finds the word book too easy", by_reflection=True)
    await remember("Prefers examples about cooking", by_reflection=False)
    await service.delete_memory(db_session, user.id, old.id)
    await send(client, conversation, "Next one")
    prompt = recorder.prompts[-1]
    assert "Prefers examples about cooking" in prompt
    assert "job interview" not in prompt and "word book too easy" not in prompt

    # Back after a break: a new sitting brings in what reflection wrote meanwhile.
    await db_session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=func.now() - service.SITTING_GAP)
    )
    await db_session.commit()
    await send(client, conversation, "I'm back")
    assert "Finds the word book too easy" in recorder.prompts[-1]
    await send(client, conversation, "And again")
    assert "Finds the word book too easy" in recorder.prompts[-1]


async def test_switching_the_chat_language_applies_from_the_next_reply(
    client: AsyncClient, recorder: PromptRecorder
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation = await new_conversation(client)

    await send(client, conversation, "Hi")
    assert "mainly in Chinese" in recorder.prompts[-1]  # no level yet (ADR 0017 §1)

    assert (await client.patch("/profile", json={"chat_language": "en"})).status_code == 200
    await send(client, conversation, "Hi again")
    assert "mainly in English" in recorder.prompts[-1]
    assert "mainly in Chinese" not in recorder.prompts[-1]


async def test_other_learners_memories_never_leak(
    client: AsyncClient, db_session: AsyncSession, recorder: PromptRecorder
) -> None:
    await login(client, "other@example.com")
    other = await db_session.scalar(select(User).where(User.email == "other@example.com"))
    assert other is not None
    other_tenant = await db_session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == other.id)
    )
    assert other_tenant is not None
    await service.add_memory(
        db_session, tenant_id=other_tenant, user_id=other.id, kind="fact", content="Secret hobby"
    )
    await client.post("/auth/logout")

    await login(client)
    await connect(client, "deepseek")
    await send(client, await new_conversation(client), "Hello")
    assert "Secret hobby" not in recorder.prompts[-1]
    assert "Things they have told you" not in recorder.prompts[-1]


async def test_every_conversation_knows_where_the_learner_is_now(
    client: AsyncClient, db_session: AsyncSession, recorder: PromptRecorder
) -> None:
    """ADR 0052 §1: a quiz done in another conversation shows in a new plain one."""
    await login(client)
    await connect(client, "deepseek")
    user = await db_session.scalar(select(User).where(User.email == "learner@example.com"))
    assert user is not None
    quiz = ExerciseSet(
        user_id=user.id,
        origin="quiz",
        quiz_purpose="quiz",
        status="ready",
        kc_plan=[],
        focus_kc_id=KC,
    )
    db_session.add(quiz)
    await db_session.flush()
    await answer(db_session, quiz.id, [True, False])

    conversation = await new_conversation(client)
    status, events, _ = await send(client, conversation, "Where was I?")

    assert status == 200 and events[-1][0] == "done"
    prompt = recorder.prompts[-1]
    assert "### Where they are now (counted by the app)" in prompt
    assert f"`{KC}`, pass quiz, finished: 1 of 2 right" in prompt
    assert "- Grammar course: on lesson" in prompt and "- Days studied in the last 7" in prompt
    [read] = [a for a in await activity(client, conversation) if a["name"] == "load_context"]
    assert read["summary"]["progress"] is True


async def test_progress_failing_keeps_the_memories_and_the_reply(
    client: AsyncClient,
    db_session: AsyncSession,
    recorder: PromptRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("course down")

    monkeypatch.setattr(learner_context, "load_progress", broken)
    await login(client)
    await connect(client, "deepseek")
    user = await db_session.scalar(select(User).where(User.email == "learner@example.com"))
    assert user is not None
    await service.update_profile(db_session, user.id, {"occupation": "nurse"}, by_learner=True)

    conversation = await new_conversation(client)
    status, events, _ = await send(client, conversation, "Hi")

    assert status == 200 and events[-1][0] == "done"
    assert "Occupation: nurse" in recorder.prompts[-1]
    assert "### Where they are now" not in recorder.prompts[-1]
    [read] = [a for a in await activity(client, conversation) if a["name"] == "load_context"]
    assert (read["status"], read["summary"]["progress"]) == ("ok", False)
